from __future__ import annotations

import queue
import threading
import time

import pytest

from ai_rescue_uwb_common import ManagedSerialTransport, SendReceipt, TransportError


class FakeLineTransport:
    def __init__(self) -> None:
        self.incoming: queue.Queue[bytes] = queue.Queue()
        self.sent: list[bytes] = []
        self.closed = False
        self.fail_reads = False

    def send_line(self, line: bytes) -> SendReceipt:
        if self.closed:
            raise TransportError("fake transport closed")
        self.sent.append(bytes(line))
        return SendReceipt(True, 1)

    def receive_line(self, timeout: float | None = None) -> bytes | None:
        if self.fail_reads:
            self.fail_reads = False
            raise TransportError("simulated USB removal")
        if self.closed:
            raise TransportError("fake transport closed")
        try:
            return self.incoming.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        self.closed = True


def wait_for(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition did not become true")


def test_missing_device_is_graceful_and_send_queue_is_bounded() -> None:
    opened: list[str] = []

    def unopened(port: str, **_: object) -> FakeLineTransport:
        opened.append(port)
        return FakeLineTransport()

    unconfigured = ManagedSerialTransport(
        "",
        opener=unopened,
        reconnect_cooldown=0.05,
        send_timeout=0.05,
    )
    try:
        wait_for(lambda: unconfigured.status().state == "unconfigured")
        assert unconfigured.status().connected is False
        assert opened == []
        with pytest.raises(TransportError, match="not configured"):
            unconfigured.send_line(b"hello")
    finally:
        unconfigured.close()

    def absent(_port: str, **_: object) -> FakeLineTransport:
        raise OSError("device absent")

    bounded = ManagedSerialTransport(
        "TEST-ABSENT",
        opener=absent,
        reconnect_initial_delay=0.02,
        reconnect_max_delay=0.02,
        reconnect_attempts=1,
        reconnect_cooldown=0.1,
        send_timeout=0.5,
        max_pending_sends=1,
    )
    first_error: list[BaseException] = []

    def first_send() -> None:
        try:
            bounded.send_line(b"first")
        except BaseException as error:
            first_error.append(error)

    thread = threading.Thread(target=first_send)
    thread.start()
    try:
        wait_for(lambda: bounded.status().queued_sends == 1)
        with pytest.raises(TransportError, match="queue is full"):
            bounded.send_line(b"second")
    finally:
        bounded.close()
        thread.join(timeout=1.0)
    assert first_error and isinstance(first_error[0], TransportError)


def test_open_send_receive_disconnect_and_bounded_reconnect() -> None:
    attempts = 0
    connections: list[FakeLineTransport] = []
    statuses = []

    def opener(port: str, **_: object) -> FakeLineTransport:
        nonlocal attempts
        assert port == "TEST0"
        attempts += 1
        if attempts <= 2:
            raise OSError(f"not ready {attempts}")
        value = FakeLineTransport()
        connections.append(value)
        return value

    transport = ManagedSerialTransport(
        "TEST0",
        opener=opener,
        reconnect_initial_delay=0.01,
        reconnect_max_delay=0.02,
        reconnect_attempts=2,
        reconnect_cooldown=0.03,
        send_timeout=1.0,
        status_callback=statuses.append,
    )
    try:
        wait_for(lambda: transport.status().connected)
        assert attempts == 3
        receipt = transport.send_line(b"first")
        assert receipt.acknowledged
        assert connections[-1].sent == [b"first"]

        connections[-1].incoming.put(b"peer-line")
        assert transport.receive_line(timeout=0.5) == b"peer-line"

        connections[-1].fail_reads = True
        wait_for(lambda: transport.status().disconnect_count >= 1)
        wait_for(lambda: transport.status().connected)
        assert len(connections) >= 2
        assert transport.send_line(b"second").acknowledged
        assert connections[-1].sent == [b"second"]

        assert any(item.state == "cooldown" for item in statuses)
        assert any(item.connected for item in statuses)
    finally:
        transport.close()
