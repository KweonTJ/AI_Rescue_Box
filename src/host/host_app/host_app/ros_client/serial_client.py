"""Pure-Python Host adapter for the existing Stage 2 UWB protocol.

The Host API continues to depend on :class:`BridgeClient`; this module is the
only Host-side production adapter that imports ``ai_rescue_uwb_common``.  ROS 2
remains available through ``RclpyBridgeClient`` as an optional development
adapter, but it is not required by the Windows product runtime.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

from ai_rescue_uwb_common import (
    ArtifactBridgeCore,
    ArtifactMetadata,
    BridgeEvent,
    BridgeEventKind,
    LineTransport,
    ManagedSerialTransport,
    SerialTransportStatus,
    SpoolManager,
)

from .bridge_client import (
    ArtifactRequest,
    BridgeClient,
    BridgeConnectionState,
    BridgeStatus,
    FeedbackCallback,
    ReceivedArtifactNotice,
    ReceivedCallback,
    SendFeedback,
    SendResult,
    StatusCallback,
)


LOGGER = logging.getLogger(__name__)


def _utc_text(timestamp: float = 0.0) -> str:
    if timestamp <= 0:
        return ""
    return (
        datetime.fromtimestamp(timestamp, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


class SerialBridgeClient(BridgeClient):
    """Thread-safe Host bridge backed by a reconnectable USB serial link.

    A missing COM port never prevents the Host API/Web application from
    starting.  Status remains ``serial_disconnected`` and local mission/map
    operations continue to work.  Transfers fail cleanly when their configured
    serial send deadline expires.
    """

    def __init__(
        self,
        *,
        port: str = "",
        baudrate: int = 460800,
        spool_dir: Path = Path("data/uwb_spool/host"),
        auto_discover: bool = False,
        firmware_ack_timeout: float = 2.0,
        firmware_max_attempts: int = 3,
        stored_ack_timeout: float = 5.0,
        application_ack_timeout: float = 30.0,
        max_repair_rounds: int = 4,
        reconnect_initial_delay: float = 0.25,
        reconnect_max_delay: float = 3.0,
        reconnect_attempts: int = 6,
        reconnect_cooldown: float = 5.0,
        send_timeout: float = 20.0,
        max_pending_sends: int = 32,
        transport: LineTransport | None = None,
        transport_factory: Callable[..., ManagedSerialTransport] = ManagedSerialTransport,
    ) -> None:
        self._lock = threading.RLock()
        self._received_listeners: list[ReceivedCallback] = []
        self._status_listeners: list[StatusCallback] = []
        self._closed = False
        self._last_retrying = False
        self._last_serial_status: SerialTransportStatus | None = None
        self._executor = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="host-serial-uwb"
        )

        self._managed_transport: ManagedSerialTransport | None = None
        if transport is None:
            managed = transport_factory(
                port,
                baudrate=baudrate,
                ack_timeout=firmware_ack_timeout,
                firmware_max_attempts=firmware_max_attempts,
                reconnect_initial_delay=reconnect_initial_delay,
                reconnect_max_delay=reconnect_max_delay,
                reconnect_attempts=reconnect_attempts,
                reconnect_cooldown=reconnect_cooldown,
                send_timeout=send_timeout,
                max_pending_sends=max_pending_sends,
                auto_discover=auto_discover,
            )
            transport = managed
            self._managed_transport = managed

        self._core = ArtifactBridgeCore(
            "host",
            SpoolManager(Path(spool_dir).expanduser()),
            transport,
            stored_ack_timeout=stored_ack_timeout,
            application_ack_timeout=application_ack_timeout,
            max_repair_rounds=max_repair_rounds,
            on_event=self._on_bridge_event,
        )
        self._core.start()
        if self._managed_transport is not None:
            self._managed_transport.add_status_listener(self._on_serial_status)
        LOGGER.info(
            "Host UWB serial adapter started port=%s baud=%s spool=%s",
            port or "<unconfigured>",
            baudrate,
            Path(spool_dir).expanduser(),
        )

    def _transport_snapshot(self) -> SerialTransportStatus | None:
        managed = self._managed_transport
        return managed.status() if managed is not None else None

    def _status_value(self) -> BridgeStatus:
        snapshot = self._core.snapshot()
        serial = self._transport_snapshot()
        serial_connected = serial.connected if serial is not None else snapshot.serial_connected
        last_error = serial.last_error if serial is not None and serial.last_error else snapshot.last_error_message
        last_error_code = snapshot.last_error_code
        if serial is not None and not serial_connected and last_error:
            last_error_code = "serial_unavailable"

        if self._closed:
            state = BridgeConnectionState.OFFLINE
        elif not serial_connected:
            state = BridgeConnectionState.SERIAL_DISCONNECTED
        elif self._last_retrying:
            state = BridgeConnectionState.RETRYING
        elif snapshot.transfer_state not in {"", "idle", "completed"}:
            state = BridgeConnectionState.TRANSFERRING
        elif snapshot.last_error_code:
            state = BridgeConnectionState.FAILED
        elif not snapshot.peer_connected:
            state = BridgeConnectionState.PEER_DISCONNECTED
        else:
            state = BridgeConnectionState.READY

        activity = max(snapshot.last_tx_time, snapshot.last_rx_time)
        return BridgeStatus(
            state=state,
            bridge_running=snapshot.running and not self._closed,
            serial_connected=serial_connected,
            peer_connected=snapshot.peer_connected and serial_connected,
            transfer_id=snapshot.transfer_id,
            bytes_sent=snapshot.bytes_sent,
            bytes_received=snapshot.bytes_received,
            retry_count=snapshot.retransmissions,
            last_error_code=last_error_code,
            last_error_message=last_error,
            last_activity_at=_utc_text(activity),
        )

    def status(self) -> BridgeStatus:
        with self._lock:
            return self._status_value()

    def _notify_status(self) -> None:
        with self._lock:
            status = self._status_value()
            listeners = tuple(self._status_listeners)
        for callback in listeners:
            try:
                callback(status)
            except Exception:
                LOGGER.exception("Host UWB status listener failed")

    def _on_serial_status(self, status: SerialTransportStatus) -> None:
        with self._lock:
            previous = self._last_serial_status
            self._last_serial_status = status

        connected_transition = status.connected and (
            previous is None
            or not previous.connected
            or previous.active_port != status.active_port
        )
        error_transition = bool(status.last_error) and (
            previous is None
            or previous.last_error != status.last_error
            or previous.state != status.state
        )

        if connected_transition:
            LOGGER.info(
                "Host UWB serial connected port=%s baud=%s",
                status.active_port,
                status.baudrate,
            )
        elif error_transition:
            LOGGER.warning(
                "Host UWB serial %s port=%s error=%s",
                status.state,
                status.active_port or status.configured_port or "<unconfigured>",
                status.last_error,
            )
        self._notify_status()

    @staticmethod
    def _feedback(event: BridgeEvent) -> SendFeedback:
        progress = (
            float(event.completed_chunks) / float(event.total_chunks)
            if event.total_chunks
            else 0.0
        )
        return SendFeedback(
            transfer_id=event.transfer_id,
            stage=event.message or event.kind.value,
            total_chunks=event.total_chunks,
            completed_chunks=event.completed_chunks,
            progress=progress,
            retry_count=event.retries,
            bytes_sent=event.bytes_sent,
        )

    def _on_bridge_event(self, event: BridgeEvent) -> None:
        with self._lock:
            self._last_retrying = event.kind is BridgeEventKind.RETRY
            received_listeners = tuple(self._received_listeners)
        if event.kind is BridgeEventKind.RECEIVED and event.artifact is not None:
            artifact = event.artifact
            metadata = artifact.metadata
            notice = ReceivedArtifactNotice(
                transfer_id=artifact.transfer_id,
                artifact_kind=metadata.artifact_type,
                mission_id=metadata.mission_id,
                artifact_version=metadata.artifact_version,
                local_path=artifact.path.resolve(),
                file_size=metadata.file_size,
                sha256=metadata.sha256,
                sender=metadata.sender,
                received_at=_utc_text(datetime.now(tz=timezone.utc).timestamp()),
            )
            LOGGER.info(
                "Host UWB received transfer=%s type=%s mission=%s version=%s bytes=%s",
                notice.transfer_id,
                notice.artifact_kind,
                notice.mission_id,
                notice.artifact_version,
                notice.file_size,
            )
            for callback in received_listeners:
                try:
                    callback(notice)
                except Exception:
                    LOGGER.exception(
                        "Host UWB received listener failed transfer=%s",
                        notice.transfer_id,
                    )
        elif event.kind in {BridgeEventKind.STORED_ACK, BridgeEventKind.APPLIED_ACK}:
            LOGGER.info(
                "Host UWB ACK transfer=%s stage=%s",
                event.transfer_id,
                event.kind.value,
            )
        elif event.kind is BridgeEventKind.RETRY:
            LOGGER.warning(
                "Host UWB retry transfer=%s retries=%s detail=%s",
                event.transfer_id,
                event.retries,
                event.message,
            )
        elif event.kind is BridgeEventKind.ERROR:
            LOGGER.error(
                "Host UWB error transfer=%s detail=%s",
                event.transfer_id,
                event.message,
            )
        self._notify_status()

    def send_artifact(
        self,
        request: ArtifactRequest,
        feedback: FeedbackCallback | None = None,
    ) -> Future[SendResult]:
        if self._closed:
            future: Future[SendResult] = Future()
            future.set_result(
                SendResult(
                    False,
                    error_code="bridge_closed",
                    error_message="Host UWB serial adapter is closed",
                )
            )
            return future

        def run() -> SendResult:
            metadata = ArtifactMetadata.from_file(
                request.local_path,
                artifact_type=request.artifact_kind,
                mission_id=request.mission_id,
                artifact_version=request.artifact_version,
                sender="host",
                priority=request.priority,
            )
            if metadata.sha256 != request.sha256:
                return SendResult(
                    False,
                    error_code="sha256_mismatch",
                    error_message="Host artifact SHA-256 changed before transmission",
                )

            def progress(event: BridgeEvent) -> None:
                if feedback is not None:
                    feedback(self._feedback(event))

            LOGGER.info(
                "Host UWB send type=%s mission=%s version=%s bytes=%s sha=%s",
                metadata.artifact_type,
                metadata.mission_id,
                metadata.artifact_version,
                metadata.file_size,
                metadata.sha256,
            )
            outcome = self._core.send_artifact(
                request.local_path,
                metadata,
                require_application_ack=request.artifact_kind != "base_map",
                progress=progress,
            )
            LOGGER.log(
                logging.INFO if outcome.success else logging.ERROR,
                "Host UWB send result transfer=%s type=%s success=%s frame_ack=%s "
                "peer_stored=%s application_ack=%s retries=%s error=%s",
                outcome.transfer_id,
                metadata.artifact_type,
                outcome.success,
                outcome.uwb_frame_ack,
                outcome.peer_saved,
                outcome.application_ack,
                outcome.retries,
                outcome.error_message,
            )
            return SendResult(
                success=outcome.success,
                transfer_id=outcome.transfer_id,
                frame_ack=outcome.uwb_frame_ack,
                remote_saved=outcome.peer_saved,
                application_ack=outcome.application_ack,
                error_code=outcome.error_code,
                error_message=outcome.error_message,
            )

        return self._executor.submit(run)

    def reconnect(self) -> Future[bool]:
        def run() -> bool:
            if self._managed_transport is None:
                return False
            self._managed_transport.request_reconnect()
            return True

        return self._executor.submit(run)

    def cancel_transfer(self, transfer_id: str) -> Future[bool]:
        return self._executor.submit(self._core.cancel_transfer, transfer_id)

    def request_resend(
        self, transfer_id: str, chunk_indices: Sequence[int]
    ) -> Future[bool]:
        def run() -> bool:
            self._core.request_resend(
                transfer_id, tuple(int(value) for value in chunk_indices)
            )
            return True

        return self._executor.submit(run)

    def acknowledge_artifact(
        self, transfer_id: str, applied: bool, error_message: str = ""
    ) -> Future[bool]:
        def run() -> bool:
            if applied:
                self._core.acknowledge_applied(transfer_id)
            else:
                self._core.reject_applied(transfer_id, error_message)
            return True

        return self._executor.submit(run)

    def add_received_listener(self, callback: ReceivedCallback) -> None:
        with self._lock:
            if callback not in self._received_listeners:
                self._received_listeners.append(callback)

    def remove_received_listener(self, callback: ReceivedCallback) -> None:
        with self._lock:
            if callback in self._received_listeners:
                self._received_listeners.remove(callback)

    def add_status_listener(self, callback: StatusCallback) -> None:
        with self._lock:
            if callback not in self._status_listeners:
                self._status_listeners.append(callback)
            status = self._status_value()
        callback(status)

    def remove_status_listener(self, callback: StatusCallback) -> None:
        with self._lock:
            if callback in self._status_listeners:
                self._status_listeners.remove(callback)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        if self._managed_transport is not None:
            self._managed_transport.remove_status_listener(self._on_serial_status)
        self._core.close()
        self._executor.shutdown(wait=False, cancel_futures=True)
        LOGGER.info("Host UWB serial adapter stopped")
        self._notify_status()
