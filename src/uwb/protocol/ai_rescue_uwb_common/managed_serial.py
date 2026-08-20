"""Reconnectable production serial transport for Host and Jetson runtimes.

The Stage 2 packet protocol remains above this module.  This layer only owns
USB-serial lifecycle, a bounded send queue, reconnect backoff and status.
"""

from __future__ import annotations

import queue
import threading
import time
from collections import deque
from dataclasses import dataclass, replace
from typing import Callable, Iterable

from .transport import (
    FirmwareLineTransport,
    LineTransport,
    SendReceipt,
    TransportError,
)


@dataclass(frozen=True)
class SerialPortCandidate:
    device: str
    description: str = ""
    hwid: str = ""
    vid: int | None = None
    pid: int | None = None


@dataclass(frozen=True)
class SerialTransportStatus:
    state: str
    configured_port: str
    active_port: str
    baudrate: int
    connected: bool
    reconnect_attempt: int
    reconnect_cycle: int
    disconnect_count: int
    queued_sends: int
    last_error: str
    last_connected_at: float
    last_disconnected_at: float


@dataclass
class _PendingSend:
    line: bytes
    deadline: float
    completed: threading.Event
    receipt: SendReceipt | None = None
    error: BaseException | None = None
    cancelled: bool = False


def discover_serial_ports() -> tuple[SerialPortCandidate, ...]:
    """Return serial candidates without guessing VID/PID or selecting a device."""

    try:
        from serial.tools import list_ports
    except ImportError:
        return ()
    values = []
    for item in list_ports.comports():
        values.append(
            SerialPortCandidate(
                device=str(getattr(item, "device", "")),
                description=str(getattr(item, "description", "") or ""),
                hwid=str(getattr(item, "hwid", "") or ""),
                vid=getattr(item, "vid", None),
                pid=getattr(item, "pid", None),
            )
        )
    return tuple(sorted(values, key=lambda value: value.device))


class ManagedSerialTransport:
    """LineTransport that survives USB removal and reconnects in bounded cycles.

    Each reconnect cycle performs at most ``reconnect_attempts`` opens.  The
    delay is exponentially backed off and capped.  After the bounded cycle the
    worker enters a cooldown, then starts another bounded cycle.  This avoids a
    tight retry loop while still recovering when a cable is plugged in later.
    """

    def __init__(
        self,
        port: str,
        *,
        baudrate: int = 460800,
        ack_timeout: float = 2.0,
        firmware_max_attempts: int = 3,
        reconnect_initial_delay: float = 0.25,
        reconnect_max_delay: float = 3.0,
        reconnect_attempts: int = 6,
        reconnect_cooldown: float = 5.0,
        send_timeout: float = 20.0,
        max_pending_sends: int = 32,
        auto_discover: bool = False,
        opener: Callable[..., LineTransport] | None = None,
        port_discovery: Callable[[], Iterable[SerialPortCandidate]] | None = None,
        status_callback: Callable[[SerialTransportStatus], None] | None = None,
    ) -> None:
        if baudrate <= 0:
            raise ValueError("baudrate must be positive")
        if ack_timeout <= 0 or firmware_max_attempts <= 0:
            raise ValueError("firmware ACK settings must be positive")
        if reconnect_initial_delay <= 0 or reconnect_max_delay <= 0:
            raise ValueError("reconnect delays must be positive")
        if reconnect_max_delay < reconnect_initial_delay:
            raise ValueError("reconnect_max_delay must be >= initial delay")
        if reconnect_attempts <= 0 or reconnect_cooldown <= 0:
            raise ValueError("reconnect attempts/cooldown must be positive")
        if send_timeout <= 0:
            raise ValueError("send_timeout must be positive")
        if max_pending_sends <= 0:
            raise ValueError("max_pending_sends must be positive")

        self.configured_port = str(port).strip()
        self.baudrate = int(baudrate)
        self.ack_timeout = float(ack_timeout)
        self.firmware_max_attempts = int(firmware_max_attempts)
        self.reconnect_initial_delay = float(reconnect_initial_delay)
        self.reconnect_max_delay = float(reconnect_max_delay)
        self.reconnect_attempts = int(reconnect_attempts)
        self.reconnect_cooldown = float(reconnect_cooldown)
        self.send_timeout = float(send_timeout)
        self.max_pending_sends = int(max_pending_sends)
        self.auto_discover = bool(auto_discover)
        self._opener = opener or FirmwareLineTransport.open
        self._port_discovery = port_discovery or discover_serial_ports
        self._status_callbacks: list[Callable[[SerialTransportStatus], None]] = []
        if status_callback is not None:
            self._status_callbacks.append(status_callback)

        self._condition = threading.Condition(threading.RLock())
        self._incoming: queue.Queue[bytes] = queue.Queue()
        self._outgoing: deque[_PendingSend] = deque()
        self._connection: LineTransport | None = None
        self._closed = False
        self._manual_reconnect = True
        self._status = SerialTransportStatus(
            state="unconfigured" if not self.configured_port and not auto_discover else "disconnected",
            configured_port=self.configured_port,
            active_port="",
            baudrate=self.baudrate,
            connected=False,
            reconnect_attempt=0,
            reconnect_cycle=0,
            disconnect_count=0,
            queued_sends=0,
            last_error=(
                "serial port is not configured"
                if not self.configured_port and not auto_discover
                else ""
            ),
            last_connected_at=0.0,
            last_disconnected_at=0.0,
        )
        self._worker = threading.Thread(
            target=self._run, name="uwb-serial-supervisor", daemon=True
        )
        self._worker.start()

    @property
    def connected(self) -> bool:
        return self.status().connected

    def add_status_listener(
        self, callback: Callable[[SerialTransportStatus], None]
    ) -> None:
        with self._condition:
            if callback not in self._status_callbacks:
                self._status_callbacks.append(callback)
            snapshot = self._status
        try:
            callback(snapshot)
        except Exception:
            pass

    def remove_status_listener(
        self, callback: Callable[[SerialTransportStatus], None]
    ) -> None:
        with self._condition:
            if callback in self._status_callbacks:
                self._status_callbacks.remove(callback)

    def status(self) -> SerialTransportStatus:
        with self._condition:
            return replace(self._status, queued_sends=len(self._outgoing))

    def request_reconnect(self) -> None:
        """Wake the supervisor and reset the current bounded reconnect cycle."""

        with self._condition:
            if self._closed:
                return
            self._manual_reconnect = True
            if self._connection is not None:
                self._disconnect_locked("manual reconnect requested", count=False)
            self._status = replace(
                self._status,
                state="disconnected",
                reconnect_attempt=0,
                last_error="",
                connected=False,
            )
            callbacks, snapshot = self._callbacks_locked()
            self._condition.notify_all()
        self._notify(callbacks, snapshot)

    def send_line(self, line: bytes) -> SendReceipt:
        payload = bytes(line)
        if not payload:
            raise TransportError("serial line must not be empty")
        with self._condition:
            if self._closed:
                raise TransportError("managed serial transport is closed")
            if not self.configured_port and not self.auto_discover:
                raise TransportError("serial port is not configured")
            if len(self._outgoing) >= self.max_pending_sends:
                raise TransportError(
                    f"serial send queue is full ({self.max_pending_sends} pending)"
                )
            pending = _PendingSend(
                line=payload,
                deadline=time.monotonic() + self.send_timeout,
                completed=threading.Event(),
            )
            self._outgoing.append(pending)
            self._manual_reconnect = True
            self._condition.notify_all()
            callbacks, snapshot = self._set_status_locked(
                queued_sends=len(self._outgoing)
            )
        self._notify(callbacks, snapshot)

        remaining = max(0.0, pending.deadline - time.monotonic())
        if not pending.completed.wait(remaining):
            with self._condition:
                pending.cancelled = True
                try:
                    self._outgoing.remove(pending)
                except ValueError:
                    pass
                callbacks, snapshot = self._set_status_locked(
                    queued_sends=len(self._outgoing),
                    last_error=f"serial send timed out after {self.send_timeout:.1f}s",
                )
                self._condition.notify_all()
            self._notify(callbacks, snapshot)
            raise TransportError(
                f"serial send timed out after {self.send_timeout:.1f}s"
            )
        if pending.error is not None:
            if isinstance(pending.error, TransportError):
                raise pending.error
            raise TransportError(str(pending.error)) from pending.error
        if pending.receipt is None:
            raise TransportError("serial send completed without a receipt")
        return pending.receipt

    def receive_line(self, timeout: float | None = None) -> bytes | None:
        if timeout is not None and timeout < 0:
            raise ValueError("timeout must be non-negative")
        try:
            return self._incoming.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._disconnect_locked("transport closed", count=False)
            error = TransportError("managed serial transport is closed")
            while self._outgoing:
                pending = self._outgoing.popleft()
                pending.error = error
                pending.completed.set()
            callbacks, snapshot = self._set_status_locked(
                state="stopped", connected=False, queued_sends=0
            )
            self._condition.notify_all()
        self._notify(callbacks, snapshot)
        self._worker.join(timeout=2.0)

    def _resolve_port(self) -> tuple[str, str]:
        if self.configured_port:
            return self.configured_port, ""
        candidates = tuple(self._port_discovery())
        if len(candidates) == 1 and candidates[0].device:
            return candidates[0].device, ""
        if not candidates:
            return "", "no serial devices were discovered"
        devices = ", ".join(value.device for value in candidates if value.device)
        return "", f"multiple serial devices found; configure one explicitly: {devices}"

    def _open(self, port: str) -> LineTransport:
        return self._opener(
            port,
            baudrate=self.baudrate,
            ack_timeout=self.ack_timeout,
            max_attempts=self.firmware_max_attempts,
        )

    def _run(self) -> None:
        attempt = 0
        cycle = 0
        next_attempt_at = 0.0
        while True:
            with self._condition:
                if self._closed:
                    return
                if self._manual_reconnect:
                    attempt = 0
                    next_attempt_at = 0.0
                    self._manual_reconnect = False
                connection = self._connection
                pending = self._next_pending_locked()

            if connection is None:
                now = time.monotonic()
                if now < next_attempt_at:
                    with self._condition:
                        self._condition.wait(timeout=min(0.1, next_attempt_at - now))
                    continue
                port, port_error = self._resolve_port()
                if not port:
                    with self._condition:
                        state = "unconfigured" if not self.auto_discover else "disconnected"
                        callbacks, snapshot = self._set_status_locked(
                            state=state,
                            active_port="",
                            connected=False,
                            last_error=port_error or "serial port is not configured",
                        )
                    self._notify(callbacks, snapshot)
                    with self._condition:
                        if not self._closed:
                            self._condition.wait(timeout=self.reconnect_cooldown)
                    continue
                attempt += 1
                with self._condition:
                    callbacks, snapshot = self._set_status_locked(
                        state="connecting",
                        active_port=port,
                        connected=False,
                        reconnect_attempt=attempt,
                        reconnect_cycle=cycle,
                        last_error="",
                    )
                self._notify(callbacks, snapshot)
                try:
                    opened = self._open(port)
                except Exception as error:
                    delay = min(
                        self.reconnect_max_delay,
                        self.reconnect_initial_delay * (2 ** max(0, attempt - 1)),
                    )
                    if attempt >= self.reconnect_attempts:
                        cycle += 1
                        attempt = 0
                        delay = self.reconnect_cooldown
                        state = "cooldown"
                    else:
                        state = "disconnected"
                    next_attempt_at = time.monotonic() + delay
                    with self._condition:
                        callbacks, snapshot = self._set_status_locked(
                            state=state,
                            connected=False,
                            reconnect_attempt=attempt,
                            reconnect_cycle=cycle,
                            last_error=str(error),
                            last_disconnected_at=time.time(),
                        )
                    self._notify(callbacks, snapshot)
                    continue
                with self._condition:
                    if self._closed:
                        try:
                            opened.close()
                        finally:
                            return
                    self._connection = opened
                    attempt = 0
                    next_attempt_at = 0.0
                    self._manual_reconnect = False
                    callbacks, snapshot = self._set_status_locked(
                        state="connected",
                        active_port=port,
                        connected=True,
                        reconnect_attempt=0,
                        reconnect_cycle=cycle,
                        last_error="",
                        last_connected_at=time.time(),
                    )
                    self._condition.notify_all()
                self._notify(callbacks, snapshot)
                continue

            if pending is not None:
                if pending.cancelled or time.monotonic() >= pending.deadline:
                    with self._condition:
                        self._remove_pending_locked(pending)
                        pending.error = TransportError("serial send deadline expired")
                        pending.completed.set()
                        callbacks, snapshot = self._set_status_locked(
                            queued_sends=len(self._outgoing),
                            last_error="serial send deadline expired",
                        )
                    self._notify(callbacks, snapshot)
                    continue
                try:
                    receipt = connection.send_line(pending.line)
                except Exception as error:
                    with self._condition:
                        self._disconnect_locked(str(error))
                        callbacks, snapshot = self._set_status_locked(
                            state="disconnected",
                            connected=False,
                            last_error=str(error),
                            last_disconnected_at=time.time(),
                        )
                        self._condition.notify_all()
                    self._notify(callbacks, snapshot)
                    next_attempt_at = time.monotonic() + self.reconnect_initial_delay
                    continue
                with self._condition:
                    self._remove_pending_locked(pending)
                    pending.receipt = receipt
                    pending.completed.set()
                    callbacks, snapshot = self._set_status_locked(
                        state="connected",
                        connected=True,
                        queued_sends=len(self._outgoing),
                        last_error="",
                    )
                    self._condition.notify_all()
                self._notify(callbacks, snapshot)

            try:
                line = connection.receive_line(timeout=0.05)
            except Exception as error:
                with self._condition:
                    self._disconnect_locked(str(error))
                    callbacks, snapshot = self._set_status_locked(
                        state="disconnected",
                        connected=False,
                        last_error=str(error),
                        last_disconnected_at=time.time(),
                    )
                    self._condition.notify_all()
                self._notify(callbacks, snapshot)
                next_attempt_at = time.monotonic() + self.reconnect_initial_delay
                continue
            if line is not None:
                self._incoming.put(bytes(line))
            if pending is None and line is None:
                with self._condition:
                    self._condition.wait(timeout=0.02)

    def _next_pending_locked(self) -> _PendingSend | None:
        while self._outgoing and self._outgoing[0].cancelled:
            self._outgoing.popleft()
        return self._outgoing[0] if self._outgoing else None

    def _remove_pending_locked(self, pending: _PendingSend) -> None:
        if self._outgoing and self._outgoing[0] is pending:
            self._outgoing.popleft()
            return
        try:
            self._outgoing.remove(pending)
        except ValueError:
            pass

    def _disconnect_locked(self, reason: str, *, count: bool = True) -> None:
        connection, self._connection = self._connection, None
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
        if count and connection is not None:
            self._status = replace(
                self._status,
                disconnect_count=self._status.disconnect_count + 1,
                last_disconnected_at=time.time(),
                last_error=reason,
            )

    def _set_status_locked(self, **changes: object) -> tuple[
        tuple[Callable[[SerialTransportStatus], None], ...], SerialTransportStatus
    ]:
        normalized = dict(changes)
        normalized["queued_sends"] = len(self._outgoing)
        updated = replace(self._status, **normalized)
        changed = updated != self._status
        self._status = updated
        callbacks = tuple(self._status_callbacks) if changed else ()
        return callbacks, updated

    def _callbacks_locked(self) -> tuple[
        tuple[Callable[[SerialTransportStatus], None], ...], SerialTransportStatus
    ]:
        return tuple(self._status_callbacks), self._status

    @staticmethod
    def _notify(
        callbacks: tuple[Callable[[SerialTransportStatus], None], ...],
        snapshot: SerialTransportStatus,
    ) -> None:
        for callback in callbacks:
            try:
                callback(snapshot)
            except Exception:
                pass
