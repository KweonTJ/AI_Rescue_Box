"""Hardware-independent artifact bridge with half-duplex transfer state."""

from __future__ import annotations

import hashlib
import heapq
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

from .protocol import (
    ACK_STAGE_APPLIED,
    ACK_STAGE_STORED,
    DATA_CHUNK_BYTES,
    AckPacket,
    ArtifactMetadata,
    CancelPacket,
    DataPacket,
    EndPacket,
    MetaPacket,
    NackPacket,
    ProtocolError,
    StartPacket,
    WirePacket,
    decode_packet,
    encode_packet,
    generate_transfer_id,
    nack_packets,
    packetize_metadata,
)
from .spool import (
    CompletedArtifact,
    IncomingArtifact,
    IncompleteTransferError,
    SpoolError,
    SpoolManager,
)
from .transport import LineTransport, TransportError


class OutboundStage(str, Enum):
    IDLE = "idle"
    QUEUED = "queued"
    SENDING = "sending"
    WAITING_STORED = "waiting_stored"
    WAITING_APPLIED = "waiting_applied"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BridgeEventKind(str, Enum):
    STARTED = "started"
    STOPPED = "stopped"
    TX_PROGRESS = "tx_progress"
    RX_PROGRESS = "rx_progress"
    RECEIVED = "received"
    STORED_ACK = "stored_ack"
    APPLIED_ACK = "applied_ack"
    RETRY = "retry"
    CANCELLED = "cancelled"
    ERROR = "error"


@dataclass(frozen=True)
class BridgeEvent:
    kind: BridgeEventKind
    transfer_id: str = ""
    message: str = ""
    completed_chunks: int = 0
    total_chunks: int = 0
    retries: int = 0
    bytes_sent: int = 0
    artifact: CompletedArtifact | None = None


@dataclass(frozen=True)
class BridgeSnapshot:
    role: str
    running: bool
    serial_connected: bool
    peer_connected: bool
    transfer_state: str
    transfer_id: str
    bytes_sent: int
    bytes_received: int
    retransmissions: int
    last_error_code: str
    last_error_message: str
    last_tx_time: float
    last_rx_time: float


@dataclass(frozen=True)
class TransferResult:
    success: bool
    transfer_id: str
    uwb_frame_ack: bool
    peer_saved: bool
    application_ack: bool
    error_code: str = ""
    error_message: str = ""
    retries: int = 0
    bytes_sent: int = 0


@dataclass
class _OutboundContext:
    transfer_id: str
    source: Path
    metadata: ArtifactMetadata
    stored: threading.Event
    applied: threading.Event
    cancelled: threading.Event
    nacks: queue.Queue[tuple[int, ...]]
    remote_error: queue.Queue[str]
    total_chunks: int
    progress: Callable[[BridgeEvent], None] | None
    start_bytes: int = 0
    retries: int = 0


class _PriorityGate:
    """Serialize whole artifacts while letting higher priority queued work lead."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._queue: list[tuple[int, int, threading.Event]] = []
        self._active = False
        self._counter = 0

    def enter(self, priority: int) -> threading.Event:
        ready = threading.Event()
        with self._condition:
            self._counter += 1
            heapq.heappush(self._queue, (-priority, self._counter, ready))
            while self._active or self._queue[0][2] is not ready:
                self._condition.wait()
            heapq.heappop(self._queue)
            self._active = True
        ready.set()
        return ready

    def leave(self) -> None:
        with self._condition:
            self._active = False
            self._condition.notify_all()


class ArtifactBridgeCore:
    """Bidirectional artifact transfer independent of ROS and pyserial.

    The firmware ACK remains the per-frame reliability mechanism.  This class
    adds peer-storage ACK, optional application ACK, missing-chunk repair,
    atomic spool completion, duplicate tolerance, cancellation and status.
    """

    def __init__(
        self,
        role: str,
        spool: SpoolManager,
        transport: LineTransport,
        *,
        stored_ack_timeout: float = 5.0,
        application_ack_timeout: float = 30.0,
        max_repair_rounds: int = 4,
        on_event: Callable[[BridgeEvent], None] | None = None,
    ) -> None:
        if role not in {"host", "jetson"}:
            raise ValueError("role must be 'host' or 'jetson'")
        if stored_ack_timeout <= 0 or application_ack_timeout <= 0:
            raise ValueError("ACK timeouts must be positive")
        if max_repair_rounds < 0:
            raise ValueError("max_repair_rounds must be non-negative")
        self.role = role
        self.spool = spool
        self.transport = transport
        self.stored_ack_timeout = stored_ack_timeout
        self.application_ack_timeout = application_ack_timeout
        self.max_repair_rounds = max_repair_rounds
        self.on_event = on_event or (lambda event: None)
        self._stop = threading.Event()
        self._reader: threading.Thread | None = None
        self._wire_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._outbound: dict[str, _OutboundContext] = {}
        self._inbound: dict[str, IncomingArtifact] = {}
        self._completed: dict[str, CompletedArtifact] = {}
        self._applied: set[str] = set()
        self._rejected: dict[str, str] = {}
        self._completed_order: deque[str] = deque(maxlen=128)
        self._send_gate = _PriorityGate()
        self._running = False
        self._serial_connected = True
        self._peer_connected = False
        self._transfer_state = OutboundStage.IDLE.value
        self._transfer_id = ""
        self._bytes_sent = 0
        self._bytes_received = 0
        self._retransmissions = 0
        self._last_error_code = ""
        self._last_error_message = ""
        self._last_tx_time = 0.0
        self._last_rx_time = 0.0

    def start(self) -> None:
        with self._state_lock:
            if self._running:
                return
            self._running = True
            self._stop.clear()
            self._reader = threading.Thread(
                target=self._receive_loop,
                name=f"uwb-{self.role}-protocol-reader",
                daemon=True,
            )
            self._reader.start()
        self._emit(BridgeEvent(BridgeEventKind.STARTED, message=f"{self.role} bridge started"))

    def close(self) -> None:
        with self._state_lock:
            if not self._running:
                return
            self._running = False
            self._stop.set()
        self.transport.close()
        if self._reader is not None and self._reader is not threading.current_thread():
            self._reader.join(timeout=1.0)
        with self._state_lock:
            for incoming in self._inbound.values():
                incoming.fail("bridge_stopped")
            self._inbound.clear()
            for context in self._outbound.values():
                context.cancelled.set()
        self._emit(BridgeEvent(BridgeEventKind.STOPPED, message=f"{self.role} bridge stopped"))

    def snapshot(self) -> BridgeSnapshot:
        with self._state_lock:
            return BridgeSnapshot(
                role=self.role,
                running=self._running,
                serial_connected=self._serial_connected,
                peer_connected=self._peer_connected,
                transfer_state=self._transfer_state,
                transfer_id=self._transfer_id,
                bytes_sent=self._bytes_sent,
                bytes_received=self._bytes_received,
                retransmissions=self._retransmissions,
                last_error_code=self._last_error_code,
                last_error_message=self._last_error_message,
                last_tx_time=self._last_tx_time,
                last_rx_time=self._last_rx_time,
            )

    def send_artifact(
        self,
        source: Path,
        metadata: ArtifactMetadata,
        *,
        transfer_id: str | None = None,
        require_application_ack: bool = True,
        progress: Callable[[BridgeEvent], None] | None = None,
    ) -> TransferResult:
        if not self._running:
            raise RuntimeError("bridge must be started before sending")
        transfer_id = generate_transfer_id() if transfer_id is None else transfer_id
        metadata_packets = packetize_metadata(transfer_id, metadata)
        data_chunks = (metadata.file_size + DATA_CHUNK_BYTES - 1) // DATA_CHUNK_BYTES
        start = StartPacket(transfer_id, len(metadata_packets), data_chunks)
        encode_packet(start)
        staged = self.spool.stage_outgoing(source, metadata)
        context = _OutboundContext(
            transfer_id=transfer_id,
            source=staged,
            metadata=metadata,
            stored=threading.Event(),
            applied=threading.Event(),
            cancelled=threading.Event(),
            nacks=queue.Queue(),
            remote_error=queue.Queue(),
            total_chunks=data_chunks,
            progress=progress,
        )
        with self._state_lock:
            if transfer_id in self._outbound:
                raise RuntimeError(f"outbound transfer already exists: {transfer_id}")
            self._outbound[transfer_id] = context
            self._set_stage(OutboundStage.QUEUED, transfer_id)

        self._send_gate.enter(metadata.priority)
        start_bytes = self.snapshot().bytes_sent
        context.start_bytes = start_bytes
        frame_ack_complete = False
        try:
            self._set_stage(OutboundStage.SENDING, transfer_id)
            self._report_progress(context, BridgeEventKind.TX_PROGRESS)
            self._check_outbound(context)
            self._transmit(start)
            for packet in metadata_packets:
                self._check_outbound(context)
                self._transmit(packet)
            digest = hashlib.sha256()
            with staged.open("rb") as stream:
                for index in range(data_chunks):
                    self._check_outbound(context)
                    data = stream.read(DATA_CHUNK_BYTES)
                    if not data:
                        raise ProtocolError("staged artifact was truncated")
                    digest.update(data)
                    self._transmit(DataPacket(transfer_id, index, data))
                    event = BridgeEvent(
                        BridgeEventKind.TX_PROGRESS,
                        transfer_id,
                        completed_chunks=index + 1,
                        total_chunks=data_chunks,
                        retries=context.retries,
                        bytes_sent=self.snapshot().bytes_sent - start_bytes,
                    )
                    self._report_progress_event(context, event)
                if stream.read(1) or digest.hexdigest() != metadata.sha256:
                    raise ProtocolError("staged artifact content changed during transmission")
            self._transmit(EndPacket(transfer_id))
            frame_ack_complete = True
            self._set_stage(OutboundStage.WAITING_STORED, transfer_id)
            self._report_progress(context, BridgeEventKind.STORED_ACK)
            self._wait_for_stored(context, data_chunks)
            if require_application_ack:
                self._set_stage(OutboundStage.WAITING_APPLIED, transfer_id)
                self._report_progress(context, BridgeEventKind.APPLIED_ACK)
                self._wait_for_application(context)
            self._set_stage(OutboundStage.COMPLETED, transfer_id)
            self._report_progress(context, BridgeEventKind.APPLIED_ACK)
            return TransferResult(
                success=True,
                transfer_id=transfer_id,
                uwb_frame_ack=True,
                peer_saved=True,
                application_ack=context.applied.is_set(),
                retries=context.retries,
                bytes_sent=self.snapshot().bytes_sent - start_bytes,
            )
        except Exception as error:
            cancelled = context.cancelled.is_set()
            code = "cancelled" if cancelled else type(error).__name__.lower()
            stage = OutboundStage.CANCELLED if cancelled else OutboundStage.FAILED
            self._set_error(code, str(error), transfer_id)
            self._set_stage(stage, transfer_id)
            return TransferResult(
                success=False,
                transfer_id=transfer_id,
                uwb_frame_ack=frame_ack_complete,
                peer_saved=context.stored.is_set(),
                application_ack=context.applied.is_set(),
                error_code=code,
                error_message=str(error),
                retries=context.retries,
                bytes_sent=self.snapshot().bytes_sent - start_bytes,
            )
        finally:
            with self._state_lock:
                self._outbound.pop(transfer_id, None)
                if self._transfer_id == transfer_id:
                    self._transfer_state = OutboundStage.IDLE.value
                    self._transfer_id = ""
            self._send_gate.leave()

    def _wait_for_stored(self, context: _OutboundContext, data_chunks: int) -> None:
        repair_round = 0
        deadline = time.monotonic() + self.stored_ack_timeout
        while not context.stored.is_set():
            self._check_outbound(context)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if repair_round >= self.max_repair_rounds:
                    raise TimeoutError(
                        f"no peer-storage ACK after {repair_round} repair rounds"
                    )
                repair_round += 1
                self._mark_retry(context.transfer_id, "repeating END after ACK timeout")
                self._transmit(EndPacket(context.transfer_id))
                deadline = time.monotonic() + self.stored_ack_timeout
                continue
            try:
                missing = context.nacks.get(timeout=min(0.05, remaining))
            except queue.Empty:
                continue
            if repair_round >= self.max_repair_rounds:
                raise TransportError("peer still reports missing chunks after repair limit")
            repair_round += 1
            self._mark_retry(
                context.transfer_id,
                f"repairing {len(missing)} missing chunks (round {repair_round})",
            )
            with context.source.open("rb") as stream:
                for index in missing:
                    if not 0 <= index < data_chunks:
                        raise ProtocolError("peer requested an out-of-range chunk")
                    stream.seek(index * DATA_CHUNK_BYTES)
                    expected = min(
                        DATA_CHUNK_BYTES,
                        context.metadata.file_size - index * DATA_CHUNK_BYTES,
                    )
                    data = stream.read(expected)
                    if len(data) != expected:
                        raise ProtocolError("cannot read requested resend chunk")
                    self._transmit(DataPacket(context.transfer_id, index, data))
            self._transmit(EndPacket(context.transfer_id))
            deadline = time.monotonic() + self.stored_ack_timeout

    def _wait_for_application(self, context: _OutboundContext) -> None:
        deadline = time.monotonic() + self.application_ack_timeout
        probe_interval = min(
            self.stored_ack_timeout,
            max(0.05, self.application_ack_timeout / 3.0),
        )
        next_probe = time.monotonic() + probe_interval
        while not context.applied.is_set():
            self._check_outbound(context)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"no application ACK within {self.application_ack_timeout:.1f}s"
                )
            until_probe = next_probe - time.monotonic()
            context.applied.wait(min(0.05, remaining, max(0.0, until_probe)))
            if not context.applied.is_set() and time.monotonic() >= next_probe:
                self._mark_retry(
                    context.transfer_id,
                    "repeating END while waiting for application ACK",
                )
                self._transmit(EndPacket(context.transfer_id))
                next_probe = time.monotonic() + probe_interval
        self._check_outbound(context)

    @staticmethod
    def _check_outbound(context: _OutboundContext) -> None:
        if context.cancelled.is_set():
            raise RuntimeError("transfer was cancelled")
        try:
            reason = context.remote_error.get_nowait()
        except queue.Empty:
            return
        raise RuntimeError(f"peer cancelled transfer: {reason}")

    def acknowledge_applied(self, transfer_id: str) -> None:
        with self._state_lock:
            if transfer_id not in self._completed:
                raise KeyError(f"no completed inbound artifact: {transfer_id}")
            self._applied.add(transfer_id)
            self._rejected.pop(transfer_id, None)
        self._transmit(AckPacket(transfer_id, ACK_STAGE_APPLIED))
        self._emit(BridgeEvent(BridgeEventKind.APPLIED_ACK, transfer_id))

    def reject_applied(self, transfer_id: str, message: str = "") -> None:
        with self._state_lock:
            if transfer_id not in self._completed:
                raise KeyError(f"no completed inbound artifact: {transfer_id}")
            self._applied.discard(transfer_id)
            self._rejected[transfer_id] = message or "receiving application rejected the artifact"
        self._transmit(CancelPacket(transfer_id, "application_rejected"))
        self._emit(
            BridgeEvent(
                BridgeEventKind.ERROR,
                transfer_id,
                message or "receiving application rejected the artifact",
            )
        )

    def request_resend(self, transfer_id: str, indices: tuple[int, ...]) -> None:
        if not indices:
            raise ValueError("at least one chunk index is required")
        for packet in nack_packets(transfer_id, indices):
            self._transmit(packet)

    def cancel_transfer(self, transfer_id: str, reason: str = "cancelled") -> bool:
        found = False
        with self._state_lock:
            context = self._outbound.get(transfer_id)
            if context is not None:
                context.cancelled.set()
                found = True
            incoming = self._inbound.pop(transfer_id, None)
            if incoming is not None:
                incoming.fail(reason)
                found = True
        if found:
            try:
                self._transmit(CancelPacket(transfer_id, reason))
            except (ProtocolError, TransportError):
                pass
            self._emit(BridgeEvent(BridgeEventKind.CANCELLED, transfer_id, reason))
        return found

    def completed_artifact(self, transfer_id: str) -> CompletedArtifact | None:
        with self._state_lock:
            return self._completed.get(transfer_id)

    def _receive_loop(self) -> None:
        while not self._stop.is_set():
            try:
                line = self.transport.receive_line(timeout=0.1)
                if line is None:
                    continue
                with self._state_lock:
                    self._bytes_received += len(line)
                    self._last_rx_time = time.time()
                    self._peer_connected = True
                packet = decode_packet(line)
                self._handle_packet(packet)
            except (ProtocolError, SpoolError) as error:
                self._set_error("receive_protocol_error", str(error))
            except TransportError as error:
                if not self._stop.is_set():
                    message = str(error)
                    with self._state_lock:
                        self._serial_connected = False
                        self._last_error_code = "transport_error"
                        self._last_error_message = message
                    self._emit(BridgeEvent(BridgeEventKind.ERROR, message=message))
                return
            except Exception as error:
                if not self._stop.is_set():
                    self._set_error("receive_error", str(error))

    def _handle_packet(self, packet: WirePacket) -> None:
        if isinstance(packet, AckPacket):
            with self._state_lock:
                context = self._outbound.get(packet.transfer_id)
            if context is None:
                return
            if packet.stage == ACK_STAGE_STORED:
                context.stored.set()
                self._emit(BridgeEvent(BridgeEventKind.STORED_ACK, packet.transfer_id))
            elif packet.stage == ACK_STAGE_APPLIED:
                context.applied.set()
                self._emit(BridgeEvent(BridgeEventKind.APPLIED_ACK, packet.transfer_id))
            return
        if isinstance(packet, NackPacket):
            with self._state_lock:
                context = self._outbound.get(packet.transfer_id)
            if context is not None:
                context.nacks.put(packet.missing_indices)
            return
        if isinstance(packet, CancelPacket):
            with self._state_lock:
                context = self._outbound.get(packet.transfer_id)
                incoming = self._inbound.pop(packet.transfer_id, None)
            if context is not None:
                context.remote_error.put(packet.reason)
            if incoming is not None:
                incoming.fail(packet.reason)
            self._emit(
                BridgeEvent(BridgeEventKind.CANCELLED, packet.transfer_id, packet.reason)
            )
            return
        if isinstance(packet, StartPacket):
            self._handle_start(packet)
            return

        with self._state_lock:
            incoming = self._inbound.get(packet.transfer_id)
            completed = self._completed.get(packet.transfer_id)
        if incoming is None:
            if completed is not None and isinstance(packet, EndPacket):
                self._transmit(AckPacket(packet.transfer_id, ACK_STAGE_STORED))
                with self._state_lock:
                    was_applied = packet.transfer_id in self._applied
                    rejection = self._rejected.get(packet.transfer_id)
                if was_applied:
                    self._transmit(AckPacket(packet.transfer_id, ACK_STAGE_APPLIED))
                elif rejection is not None:
                    self._transmit(CancelPacket(packet.transfer_id, "application_rejected"))
            return
        try:
            if isinstance(packet, MetaPacket):
                incoming.accept_metadata_chunk(packet.index, packet.data)
            elif isinstance(packet, DataPacket):
                incoming.accept_data_chunk(packet.index, packet.data)
                self._emit(
                    BridgeEvent(
                        BridgeEventKind.RX_PROGRESS,
                        packet.transfer_id,
                        completed_chunks=incoming.received_count,
                        total_chunks=incoming.data_chunk_count,
                    )
                )
            elif isinstance(packet, EndPacket):
                self._finish_incoming(incoming)
        except (ProtocolError, SpoolError) as error:
            incoming.fail("invalid_transfer")
            with self._state_lock:
                self._inbound.pop(packet.transfer_id, None)
            self._transmit(CancelPacket(packet.transfer_id, "invalid_transfer"))
            self._set_error("invalid_transfer", str(error), packet.transfer_id)

    def _handle_start(self, packet: StartPacket) -> None:
        with self._state_lock:
            completed = packet.transfer_id in self._completed
            applied = packet.transfer_id in self._applied
            rejected = packet.transfer_id in self._rejected
            existing = self._inbound.get(packet.transfer_id)
        if completed:
            self._transmit(AckPacket(packet.transfer_id, ACK_STAGE_STORED))
            if applied:
                self._transmit(AckPacket(packet.transfer_id, ACK_STAGE_APPLIED))
            elif rejected:
                self._transmit(CancelPacket(packet.transfer_id, "application_rejected"))
            return
        if existing is not None:
            changed = (
                existing.metadata_chunk_count != packet.metadata_chunks
                or existing.data_chunk_count != packet.data_chunks
            )
            if changed:
                existing.fail("start_changed")
                with self._state_lock:
                    self._inbound.pop(packet.transfer_id, None)
                self._transmit(CancelPacket(packet.transfer_id, "start_changed"))
            return
        incoming = self.spool.begin_incoming(
            packet.transfer_id, packet.metadata_chunks, packet.data_chunks
        )
        with self._state_lock:
            if packet.transfer_id in self._inbound:
                incoming.fail("duplicate_start")
                return
            self._inbound[packet.transfer_id] = incoming

    def _finish_incoming(self, incoming: IncomingArtifact) -> None:
        if not incoming.metadata_complete:
            self._transmit(CancelPacket(incoming.transfer_id, "metadata_incomplete"))
            return
        try:
            artifact = incoming.complete()
        except IncompleteTransferError as error:
            for packet in nack_packets(incoming.transfer_id, error.missing_indices):
                self._transmit(packet)
            return
        with self._state_lock:
            self._inbound.pop(incoming.transfer_id, None)
            if len(self._completed_order) == self._completed_order.maxlen:
                oldest = self._completed_order.popleft()
                self._completed.pop(oldest, None)
                self._applied.discard(oldest)
                self._rejected.pop(oldest, None)
            self._completed_order.append(incoming.transfer_id)
            self._completed[incoming.transfer_id] = artifact
            self._last_error_code = ""
            self._last_error_message = ""
        self._transmit(AckPacket(incoming.transfer_id, ACK_STAGE_STORED))
        self._emit(
            BridgeEvent(
                BridgeEventKind.RECEIVED,
                incoming.transfer_id,
                completed_chunks=incoming.data_chunk_count,
                total_chunks=incoming.data_chunk_count,
                artifact=artifact,
            )
        )

    def _transmit(self, packet: WirePacket) -> None:
        line = encode_packet(packet)
        try:
            with self._wire_lock:
                receipt = self.transport.send_line(line)
        except TransportError:
            with self._state_lock:
                self._peer_connected = False
            raise
        with self._state_lock:
            self._bytes_sent += len(line)
            self._last_tx_time = time.time()
            self._peer_connected = receipt.acknowledged
            if receipt.attempts > 1:
                self._retransmissions += receipt.attempts - 1
        if receipt.attempts > 1:
            event = BridgeEvent(
                BridgeEventKind.RETRY,
                packet.transfer_id,
                message="firmware line retry",
                retries=receipt.attempts - 1,
            )
            self._emit(event)
            self._report_outbound_callback(event)

    def _mark_retry(self, transfer_id: str, message: str) -> None:
        with self._state_lock:
            self._retransmissions += 1
        event = BridgeEvent(
            BridgeEventKind.RETRY,
            transfer_id,
            message=message,
            retries=1,
        )
        self._emit(event)
        self._report_outbound_callback(event)

    def _set_stage(self, stage: OutboundStage, transfer_id: str) -> None:
        with self._state_lock:
            self._transfer_state = stage.value
            self._transfer_id = transfer_id
            if stage in {OutboundStage.SENDING, OutboundStage.COMPLETED}:
                self._last_error_code = ""
                self._last_error_message = ""

    def _report_progress(
        self, context: _OutboundContext, kind: BridgeEventKind
    ) -> None:
        stage = self.snapshot().transfer_state
        completed_chunks = (
            0 if stage in {OutboundStage.QUEUED.value, OutboundStage.SENDING.value}
            else context.total_chunks
        )
        event = BridgeEvent(
            kind,
            context.transfer_id,
            message=stage,
            completed_chunks=completed_chunks,
            total_chunks=context.total_chunks,
            retries=context.retries,
            bytes_sent=self.snapshot().bytes_sent - context.start_bytes,
        )
        if context.progress is not None:
            try:
                context.progress(event)
            except Exception:
                pass

    def _report_progress_event(
        self, context: _OutboundContext, event: BridgeEvent
    ) -> None:
        self._emit(event)
        if context.progress is not None:
            try:
                context.progress(event)
            except Exception:
                pass

    def _report_outbound_callback(self, event: BridgeEvent) -> None:
        with self._state_lock:
            context = self._outbound.get(event.transfer_id)
            if context is not None and event.kind is BridgeEventKind.RETRY:
                context.retries += event.retries
            transfer_retries = context.retries if context is not None else 0
        if context is not None and context.progress is not None:
            try:
                context.progress(
                    BridgeEvent(
                        event.kind,
                        event.transfer_id,
                        message=(
                            OutboundStage.SENDING.value
                            if event.kind is BridgeEventKind.RETRY
                            else event.message
                        ),
                        completed_chunks=event.completed_chunks,
                        total_chunks=context.total_chunks,
                        retries=transfer_retries,
                        bytes_sent=self.snapshot().bytes_sent - context.start_bytes,
                    )
                )
            except Exception:
                pass

    def _set_error(self, code: str, message: str, transfer_id: str = "") -> None:
        with self._state_lock:
            self._last_error_code = code
            self._last_error_message = message
        self._emit(BridgeEvent(BridgeEventKind.ERROR, transfer_id, message))

    def _emit(self, event: BridgeEvent) -> None:
        try:
            self.on_event(event)
        except Exception:
            pass
