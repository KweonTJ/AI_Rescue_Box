"""Line transports for the ESP32 bridge and deterministic in-memory tests."""

from __future__ import annotations

import fcntl
import hashlib
import os
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol, runtime_checkable

from .protocol import MAX_WIRE_PAYLOAD_BYTES


class TransportError(RuntimeError):
    """The local serial bridge could not acknowledge or carry a line."""


@dataclass(frozen=True)
class SendReceipt:
    acknowledged: bool
    attempts: int
    response: str = "[UWB ACK]"


@runtime_checkable
class LineTransport(Protocol):
    """A half-duplex newline transport whose send waits for link-layer ACK."""

    def send_line(self, line: bytes) -> SendReceipt:
        ...

    def receive_line(self, timeout: float | None = None) -> bytes | None:
        ...

    def close(self) -> None:
        ...


class ExclusivePortLock:
    """Cross-process advisory lock preventing two bridges owning one port."""

    def __init__(self, port: str, lock_directory: Path | None = None) -> None:
        directory = Path("/tmp/ai_rescue_uwb_locks") if lock_directory is None else lock_directory
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        key = hashlib.sha256(os.path.realpath(port).encode("utf-8")).hexdigest()[:20]
        self.path = directory / f"port-{key}.lock"
        self._stream = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(self._stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            self._stream.close()
            raise TransportError(f"serial port is already owned by another bridge: {port}") from error
        self._stream.seek(0)
        self._stream.truncate()
        self._stream.write(f"pid={os.getpid()}\nport={os.path.realpath(port)}\n")
        self._stream.flush()

    def close(self) -> None:
        if self._stream.closed:
            return
        fcntl.flock(self._stream.fileno(), fcntl.LOCK_UN)
        self._stream.close()


class FirmwareLineTransport:
    """Adapter for the existing `[UWB ACK]` ESP32 USB-serial contract."""

    def __init__(
        self,
        connection: object,
        *,
        port_lock: ExclusivePortLock | None = None,
        ack_timeout: float = 2.0,
        max_attempts: int = 3,
    ) -> None:
        if ack_timeout <= 0 or max_attempts <= 0:
            raise ValueError("ack_timeout and max_attempts must be positive")
        self.connection = connection
        self.port_lock = port_lock
        self.ack_timeout = ack_timeout
        self.max_attempts = max_attempts
        self._incoming: queue.Queue[bytes] = queue.Queue()
        self._feedback: queue.Queue[tuple[bool, str]] = queue.Queue()
        self._reader_error: str | None = None
        self._reader_error_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._retry_lock = threading.Lock()
        self._firmware_retry_count = 0
        self._stop = threading.Event()
        self._reader = threading.Thread(
            target=self._read_loop, name="uwb-firmware-reader", daemon=True
        )
        self._reader.start()

    @classmethod
    def open(
        cls,
        port: str,
        *,
        baudrate: int = 460800,
        ack_timeout: float = 2.0,
        max_attempts: int = 3,
        serial_timeout: float = 0.1,
    ) -> "FirmwareLineTransport":
        if baudrate <= 0:
            raise TransportError("baudrate must be positive")
        port_lock = ExclusivePortLock(port)
        try:
            try:
                import serial
            except ImportError as error:
                raise TransportError(
                    "pyserial is required for a hardware bridge"
                ) from error
            try:
                connection = serial.Serial(
                    port=port,
                    baudrate=baudrate,
                    timeout=serial_timeout,
                    write_timeout=1.0,
                    exclusive=True,
                )
            except TypeError:
                connection = serial.Serial(
                    port=port,
                    baudrate=baudrate,
                    timeout=serial_timeout,
                    write_timeout=1.0,
                )
            connection.reset_input_buffer()
            return cls(
                connection,
                port_lock=port_lock,
                ack_timeout=ack_timeout,
                max_attempts=max_attempts,
            )
        except Exception:
            port_lock.close()
            raise

    def _read_loop(self) -> None:
        pending = bytearray()
        while not self._stop.is_set():
            try:
                data = self.connection.readline()
            except Exception as error:
                if not self._stop.is_set():
                    message = f"serial reader stopped: {error}"
                    with self._reader_error_lock:
                        self._reader_error = message
                    self._feedback.put((False, message))
                return
            if not data:
                continue
            pending.extend(data)
            while b"\n" in pending:
                raw, _, remainder = pending.partition(b"\n")
                pending = bytearray(remainder)
                line = bytes(raw).rstrip(b"\r")
                if not line:
                    continue
                if line == b"[UWB ACK]":
                    self._feedback.put((True, "[UWB ACK]"))
                elif line.startswith(b"[UWB ERROR]"):
                    self._feedback.put((False, line.decode("utf-8", errors="replace")))
                elif line.startswith(b"[UWB RETRY]"):
                    with self._retry_lock:
                        self._firmware_retry_count += 1
                elif line.startswith(b"[UWB "):
                    continue
                else:
                    self._incoming.put(line)

    def send_line(self, line: bytes) -> SendReceipt:
        payload = bytes(line)
        if not payload or len(payload) > MAX_WIRE_PAYLOAD_BYTES:
            raise TransportError(
                f"line must contain 1..{MAX_WIRE_PAYLOAD_BYTES} payload bytes"
            )
        if b"\r" in payload or b"\n" in payload:
            raise TransportError("line payload must not contain CR or LF")
        with self._send_lock:
            with self._retry_lock:
                retry_count_before = self._firmware_retry_count
            while True:
                try:
                    self._feedback.get_nowait()
                except queue.Empty:
                    break
            last_error = "link ACK timed out"
            for attempt in range(1, self.max_attempts + 1):
                try:
                    self.connection.write(payload + b"\n")
                    self.connection.flush()
                except Exception as error:
                    last_error = f"serial write failed: {error}"
                    continue
                try:
                    success, response = self._feedback.get(timeout=self.ack_timeout)
                except queue.Empty:
                    last_error = f"no firmware ACK within {self.ack_timeout:.1f}s"
                    continue
                if success:
                    with self._retry_lock:
                        firmware_retries = (
                            self._firmware_retry_count - retry_count_before
                        )
                    return SendReceipt(
                        True, attempt + firmware_retries, response
                    )
                last_error = response
            raise TransportError(
                f"link delivery failed after {self.max_attempts} attempts: {last_error}"
            )

    def receive_line(self, timeout: float | None = None) -> bytes | None:
        try:
            return self._incoming.get(timeout=timeout)
        except queue.Empty:
            with self._reader_error_lock:
                error = self._reader_error
            if error is not None:
                raise TransportError(error)
            return None

    def close(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        try:
            self.connection.close()
        finally:
            self._reader.join(timeout=1.0)
            if self.port_lock is not None:
                self.port_lock.close()


class InMemoryEndpoint:
    """Deterministic acknowledged link endpoint used by tests and mock CLI."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._peer: "InMemoryEndpoint | None" = None
        self._incoming: queue.Queue[bytes] = queue.Queue()
        self._closed = False
        self.sent_count = 0
        self.sent_lines: list[bytes] = []
        self.retry_count = 0
        self.lost_delivery_count = 0
        self.drop_once: Callable[[bytes], bool] | None = None
        self.lose_delivery_once: Callable[[bytes], bool] | None = None
        self._already_dropped: set[bytes] = set()
        self._already_lost: set[bytes] = set()

    def connect(self, peer: "InMemoryEndpoint") -> None:
        self._peer = peer

    def send_line(self, line: bytes) -> SendReceipt:
        if self._closed:
            raise TransportError(f"mock endpoint {self.name} is closed")
        if self._peer is None or self._peer._closed:
            raise TransportError(f"mock endpoint {self.name} has no connected peer")
        payload = bytes(line)
        if not payload or len(payload) > MAX_WIRE_PAYLOAD_BYTES:
            raise TransportError("mock line exceeds the firmware payload limit")
        self.sent_count += 1
        self.sent_lines.append(payload)
        attempts = 1
        if (
            self.drop_once is not None
            and payload not in self._already_dropped
            and self.drop_once(payload)
        ):
            self._already_dropped.add(payload)
            attempts = 2
            self.retry_count += 1
        if (
            self.lose_delivery_once is not None
            and payload not in self._already_lost
            and self.lose_delivery_once(payload)
        ):
            self._already_lost.add(payload)
            self.lost_delivery_count += 1
        else:
            self._peer._incoming.put(payload)
        return SendReceipt(True, attempts)

    def inject_received(self, line: bytes) -> None:
        self._incoming.put(bytes(line))

    def receive_line(self, timeout: float | None = None) -> bytes | None:
        if self._closed:
            return None
        try:
            return self._incoming.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        self._closed = True


def create_memory_link() -> tuple[InMemoryEndpoint, InMemoryEndpoint]:
    first = InMemoryEndpoint("host")
    second = InMemoryEndpoint("jetson")
    first.connect(second)
    second.connect(first)
    return first, second
