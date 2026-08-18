"""Thread-safe facade for a separately running ROS2 UWB Bridge.

This module deliberately contains no serial transport. A concrete rclpy adapter
can implement :class:`BridgeClient` and be attached after ROS discovery; until
then, the app remains fully usable with :class:`OfflineBridgeClient`.
"""

from __future__ import annotations

import hashlib
import os
import threading
from abc import ABC, abstractmethod
from concurrent.futures import Future, InvalidStateError
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Sequence

from ..errors import ValidationError
from ..mission.models import SHA256_RE, positive_int, validate_mission_id
from ..storage.spool import ARTIFACT_KINDS


class BridgeConnectionState(str, Enum):
    OFFLINE = "bridge_offline"
    BRIDGE_READY = "bridge_ready"
    SERIAL_DISCONNECTED = "serial_disconnected"
    PEER_DISCONNECTED = "peer_disconnected"
    READY = "ready"
    TRANSFERRING = "transferring"
    RETRYING = "retrying"
    FAILED = "failed"


@dataclass(frozen=True)
class BridgeStatus:
    state: BridgeConnectionState = BridgeConnectionState.OFFLINE
    bridge_running: bool = False
    serial_connected: bool = False
    peer_connected: bool = False
    transfer_id: str = ""
    bytes_sent: int = 0
    bytes_received: int = 0
    retry_count: int = 0
    last_error_code: str = ""
    last_error_message: str = ""
    last_activity_at: str = ""


@dataclass(frozen=True)
class ArtifactRequest:
    artifact_kind: str
    local_path: Path
    mission_id: str
    artifact_version: int
    sha256: str
    priority: int = 0

    def __post_init__(self) -> None:
        if self.artifact_kind not in ARTIFACT_KINDS:
            raise ValidationError("unsupported artifact kind")
        path = Path(self.local_path).expanduser()
        if not path.is_file() or path.is_symlink():
            raise ValidationError("artifact path must be a regular local file")
        object.__setattr__(self, "local_path", path.resolve())
        object.__setattr__(self, "mission_id", validate_mission_id(self.mission_id))
        object.__setattr__(
            self, "artifact_version", positive_int(self.artifact_version, "artifact_version")
        )
        if not isinstance(self.sha256, str) or SHA256_RE.fullmatch(self.sha256) is None:
            raise ValidationError("sha256 must be 64 lowercase hex characters")
        if (
            isinstance(self.priority, bool)
            or not isinstance(self.priority, int)
            or not 0 <= self.priority <= 255
        ):
            raise ValidationError("priority must be an integer between 0 and 255")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != self.sha256:
            raise ValidationError("artifact SHA-256 does not match local file")


@dataclass(frozen=True)
class SendFeedback:
    transfer_id: str
    stage: str
    total_chunks: int
    completed_chunks: int
    progress: float
    retry_count: int
    bytes_sent: int


@dataclass(frozen=True)
class SendResult:
    success: bool
    transfer_id: str = ""
    frame_ack: bool = False
    remote_saved: bool = False
    application_ack: bool = False
    error_code: str = ""
    error_message: str = ""


@dataclass(frozen=True)
class ReceivedArtifactNotice:
    transfer_id: str
    artifact_kind: str
    mission_id: str
    artifact_version: int
    local_path: Path
    file_size: int
    sha256: str
    sender: str
    received_at: str


FeedbackCallback = Callable[[SendFeedback], None]
StatusCallback = Callable[[BridgeStatus], None]
ReceivedCallback = Callable[[ReceivedArtifactNotice], None]
RECEIVED_ARTIFACT_QOS_DEPTH = 64


def _transient_artifact_qos(
    qos_profile_type: type, reliability_policy: object, durability_policy: object
) -> object:
    profile = qos_profile_type(depth=RECEIVED_ARTIFACT_QOS_DEPTH)
    profile.reliability = reliability_policy.RELIABLE
    profile.durability = durability_policy.TRANSIENT_LOCAL
    return profile


class BridgeClient(ABC):
    @abstractmethod
    def status(self) -> BridgeStatus:
        pass

    @abstractmethod
    def send_artifact(
        self,
        request: ArtifactRequest,
        feedback: FeedbackCallback | None = None,
    ) -> Future[SendResult]:
        pass

    def reconnect(self) -> Future[bool]:
        future: Future[bool] = Future()
        future.set_result(False)
        return future

    def cancel_transfer(self, transfer_id: str) -> Future[bool]:
        future: Future[bool] = Future()
        future.set_result(False)
        return future

    def request_resend(
        self, transfer_id: str, chunk_indices: Sequence[int]
    ) -> Future[bool]:
        future: Future[bool] = Future()
        future.set_result(False)
        return future

    def acknowledge_artifact(
        self, transfer_id: str, applied: bool, error_message: str = ""
    ) -> Future[bool]:
        future: Future[bool] = Future()
        future.set_result(False)
        return future

    def add_received_listener(self, callback: ReceivedCallback) -> None:
        pass

    def remove_received_listener(self, callback: ReceivedCallback) -> None:
        pass

    def add_status_listener(self, callback: StatusCallback) -> None:
        pass

    def remove_status_listener(self, callback: StatusCallback) -> None:
        pass

    def close(self) -> None:
        pass


class OfflineBridgeClient(BridgeClient):
    def status(self) -> BridgeStatus:
        return BridgeStatus(
            state=BridgeConnectionState.OFFLINE,
            last_error_code="BRIDGE_UNAVAILABLE",
            last_error_message="UWB Bridge가 실행되지 않았습니다.",
        )

    def send_artifact(
        self,
        request: ArtifactRequest,
        feedback: FeedbackCallback | None = None,
    ) -> Future[SendResult]:
        future: Future[SendResult] = Future()
        future.set_result(
            SendResult(
                success=False,
                error_code="BRIDGE_UNAVAILABLE",
                error_message="UWB Bridge가 실행되지 않았습니다.",
            )
        )
        return future


class HostBridgeFacade:
    def __init__(self, client: BridgeClient | None = None):
        self._lock = threading.RLock()
        self._client: BridgeClient = client or OfflineBridgeClient()
        self._listeners: list[StatusCallback] = []
        self._received_listeners: list[ReceivedCallback] = []
        self._client.add_status_listener(self._relay_status)

    def _relay_status(self, status: BridgeStatus) -> None:
        with self._lock:
            listeners = tuple(self._listeners)
        for callback in listeners:
            callback(status)

    def attach(self, client: BridgeClient) -> None:
        if not isinstance(client, BridgeClient):
            raise TypeError("client must implement BridgeClient")
        with self._lock:
            previous = self._client
            self._client = client
            received_listeners = tuple(self._received_listeners)
        previous.remove_status_listener(self._relay_status)
        client.add_status_listener(self._relay_status)
        for listener in received_listeners:
            previous.remove_received_listener(listener)
            client.add_received_listener(listener)
        if previous is not client:
            previous.close()
        self.notify_status()

    def detach(self) -> None:
        self.attach(OfflineBridgeClient())

    def add_status_listener(self, callback: StatusCallback) -> None:
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)
        callback(self.status())

    def remove_status_listener(self, callback: StatusCallback) -> None:
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    def add_received_listener(self, callback: ReceivedCallback) -> None:
        with self._lock:
            if callback in self._received_listeners:
                return
            self._received_listeners.append(callback)
            client = self._client
        client.add_received_listener(callback)

    def remove_received_listener(self, callback: ReceivedCallback) -> None:
        with self._lock:
            if callback not in self._received_listeners:
                return
            self._received_listeners.remove(callback)
            client = self._client
        client.remove_received_listener(callback)

    def notify_status(self) -> None:
        current = self.status()
        with self._lock:
            listeners = tuple(self._listeners)
        for callback in listeners:
            callback(current)

    def status(self) -> BridgeStatus:
        with self._lock:
            return self._client.status()

    def send_artifact(
        self,
        request: ArtifactRequest,
        feedback: FeedbackCallback | None = None,
    ) -> Future[SendResult]:
        with self._lock:
            client = self._client
        return client.send_artifact(request, feedback)

    def reconnect(self) -> Future[bool]:
        with self._lock:
            return self._client.reconnect()

    def cancel_transfer(self, transfer_id: str) -> Future[bool]:
        with self._lock:
            return self._client.cancel_transfer(transfer_id)

    def request_resend(
        self, transfer_id: str, chunk_indices: Sequence[int]
    ) -> Future[bool]:
        with self._lock:
            return self._client.request_resend(transfer_id, chunk_indices)

    def acknowledge_artifact(
        self, transfer_id: str, applied: bool, error_message: str = ""
    ) -> Future[bool]:
        with self._lock:
            return self._client.acknowledge_artifact(
                transfer_id, applied, error_message
            )

    def close(self) -> None:
        with self._lock:
            client = self._client
            self._client = OfflineBridgeClient()
        client.close()


def _ros_time_text(value: object) -> str:
    seconds = int(getattr(value, "sec", 0))
    nanoseconds = int(getattr(value, "nanosec", 0))
    if seconds <= 0:
        return ""
    instant = datetime.fromtimestamp(
        seconds + nanoseconds / 1_000_000_000, tz=timezone.utc
    )
    return instant.isoformat().replace("+00:00", "Z")


class RclpyBridgeClient(BridgeClient):
    def __init__(
        self,
        node_name: str = "ai_rescue_box_host_client",
        *,
        status_topic: str = "/uwb/status",
        received_topic: str = "/uwb/received_artifact",
        send_action: str = "/uwb/send_artifact",
        reconnect_service: str = "/uwb/reconnect",
        cancel_service: str = "/uwb/cancel_transfer",
        resend_service: str = "/uwb/request_resend",
        acknowledge_service: str = "/uwb/acknowledge_artifact",
    ) -> None:
        os.environ.setdefault("ROS_LOCALHOST_ONLY", "1")
        try:
            import rclpy
            from rclpy.action import ActionClient
            from rclpy.callback_groups import ReentrantCallbackGroup
            from rclpy.context import Context
            from rclpy.executors import MultiThreadedExecutor
            from rclpy.node import Node
            from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
            from uwb_interfaces.action import SendArtifact
            from uwb_interfaces.msg import ReceivedArtifact, UwbStatus
            from uwb_interfaces.srv import (
                AcknowledgeArtifact,
                CancelTransfer,
                Reconnect,
                RequestResend,
            )
        except ImportError as error:
            raise RuntimeError(
                "ROS2 rclpy 또는 uwb_interfaces를 찾을 수 없습니다. "
                "ROS2 및 colcon setup.bash를 source 하세요."
            ) from error

        self._rclpy = rclpy
        self._types = {
            "SendArtifact": SendArtifact,
            "Reconnect": Reconnect,
            "CancelTransfer": CancelTransfer,
            "RequestResend": RequestResend,
            "AcknowledgeArtifact": AcknowledgeArtifact,
        }
        self._lock = threading.RLock()
        self._status = BridgeStatus()
        self._status_listeners: list[StatusCallback] = []
        self._received_listeners: list[ReceivedCallback] = []
        self._closed = False
        self._context = Context()
        rclpy.init(args=None, context=self._context)
        self._node = Node(node_name, context=self._context)
        callback_group = ReentrantCallbackGroup()
        status_qos = QoSProfile(depth=1)
        status_qos.reliability = ReliabilityPolicy.RELIABLE
        status_qos.durability = DurabilityPolicy.TRANSIENT_LOCAL
        self._status_subscription = self._node.create_subscription(
            UwbStatus,
            status_topic,
            self._on_status,
            status_qos,
            callback_group=callback_group,
        )
        received_qos = _transient_artifact_qos(
            QoSProfile, ReliabilityPolicy, DurabilityPolicy
        )
        self._received_subscription = self._node.create_subscription(
            ReceivedArtifact,
            received_topic,
            self._on_received,
            received_qos,
            callback_group=callback_group,
        )
        self._action = ActionClient(
            self._node,
            SendArtifact,
            send_action,
            callback_group=callback_group,
        )
        self._reconnect_client = self._node.create_client(
            Reconnect, reconnect_service, callback_group=callback_group
        )
        self._cancel_client = self._node.create_client(
            CancelTransfer, cancel_service, callback_group=callback_group
        )
        self._resend_client = self._node.create_client(
            RequestResend, resend_service, callback_group=callback_group
        )
        self._ack_client = self._node.create_client(
            AcknowledgeArtifact,
            acknowledge_service,
            callback_group=callback_group,
        )
        self._executor = MultiThreadedExecutor(num_threads=2, context=self._context)
        self._executor.add_node(self._node)
        self._spin_thread = threading.Thread(
            target=self._spin,
            name="host-rclpy-executor",
            daemon=True,
        )
        self._spin_thread.start()

    def _spin(self) -> None:
        try:
            self._executor.spin()
        except Exception:
            if not self._closed:
                with self._lock:
                    self._status = BridgeStatus(
                        state=BridgeConnectionState.FAILED,
                        last_error_code="ROS_EXECUTOR_ERROR",
                        last_error_message="ROS2 executor가 중지되었습니다.",
                    )

    @staticmethod
    def _state_from_message(message: object) -> BridgeConnectionState:
        transfer_state = str(getattr(message, "transfer_state", "")).lower()
        if transfer_state in {
            "queued",
            "sending",
            "receiving",
            "transferring",
            "awaiting_ack",
            "waiting_stored",
            "waiting_applied",
        }:
            return BridgeConnectionState.TRANSFERRING
        if "retry" in transfer_state or "resend" in transfer_state:
            return BridgeConnectionState.RETRYING
        if getattr(message, "last_error_code", ""):
            return BridgeConnectionState.FAILED
        if not getattr(message, "bridge_running", False):
            return BridgeConnectionState.OFFLINE
        if not getattr(message, "serial_connected", False):
            return BridgeConnectionState.SERIAL_DISCONNECTED
        if not getattr(message, "peer_connected", False):
            return BridgeConnectionState.PEER_DISCONNECTED
        return BridgeConnectionState.READY

    def _on_status(self, message: object) -> None:
        tx_time = _ros_time_text(getattr(message, "last_tx_time", object()))
        rx_time = _ros_time_text(getattr(message, "last_rx_time", object()))
        last_activity = max(tx_time, rx_time) if tx_time and rx_time else tx_time or rx_time
        status = BridgeStatus(
            state=self._state_from_message(message),
            bridge_running=bool(message.bridge_running),
            serial_connected=bool(message.serial_connected),
            peer_connected=bool(message.peer_connected),
            transfer_id=str(message.transfer_id),
            bytes_sent=int(message.bytes_sent),
            bytes_received=int(message.bytes_received),
            retry_count=int(message.retransmission_count),
            last_error_code=str(message.last_error_code),
            last_error_message=str(message.last_error_message),
            last_activity_at=last_activity,
        )
        with self._lock:
            self._status = status
            listeners = tuple(self._status_listeners)
        for callback in listeners:
            callback(status)

    def _on_received(self, message: object) -> None:
        notice = ReceivedArtifactNotice(
            transfer_id=str(message.transfer_id),
            artifact_kind=str(message.artifact_type),
            mission_id=str(message.mission_id),
            artifact_version=int(message.artifact_version),
            local_path=Path(str(message.local_file_path)),
            file_size=int(message.file_size),
            sha256=str(message.sha256),
            sender=str(message.sender),
            received_at=_ros_time_text(message.received_at),
        )
        with self._lock:
            listeners = tuple(self._received_listeners)
        for callback in listeners:
            callback(notice)

    def status(self) -> BridgeStatus:
        with self._lock:
            return self._status

    def add_status_listener(self, callback: StatusCallback) -> None:
        with self._lock:
            if callback not in self._status_listeners:
                self._status_listeners.append(callback)

    def remove_status_listener(self, callback: StatusCallback) -> None:
        with self._lock:
            if callback in self._status_listeners:
                self._status_listeners.remove(callback)

    def add_received_listener(self, callback: ReceivedCallback) -> None:
        with self._lock:
            if callback not in self._received_listeners:
                self._received_listeners.append(callback)

    def remove_received_listener(self, callback: ReceivedCallback) -> None:
        with self._lock:
            if callback in self._received_listeners:
                self._received_listeners.remove(callback)

    def send_artifact(
        self,
        request: ArtifactRequest,
        feedback: FeedbackCallback | None = None,
    ) -> Future[SendResult]:
        result_future: Future[SendResult] = Future()

        def set_result(value: SendResult) -> None:
            try:
                result_future.set_result(value)
            except InvalidStateError:
                pass

        def set_exception(error: BaseException) -> None:
            try:
                result_future.set_exception(error)
            except InvalidStateError:
                pass

        if self._closed or not self._action.server_is_ready():
            set_result(
                SendResult(
                    False,
                    error_code="BRIDGE_UNAVAILABLE",
                    error_message="/uwb/send_artifact Action server를 찾을 수 없습니다.",
                )
            )
            return result_future

        goal = self._types["SendArtifact"].Goal()
        goal.artifact_type = request.artifact_kind
        goal.local_file_path = str(request.local_path)
        goal.mission_id = request.mission_id
        goal.artifact_version = request.artifact_version
        goal.sha256 = request.sha256
        goal.priority = request.priority

        def on_feedback(message: object) -> None:
            if feedback is None:
                return
            value = message.feedback
            feedback(
                SendFeedback(
                    transfer_id=str(value.transfer_id),
                    stage=str(value.stage),
                    total_chunks=int(value.total_chunks),
                    completed_chunks=int(value.completed_chunks),
                    progress=float(value.progress),
                    retry_count=int(value.retransmission_count),
                    bytes_sent=int(value.bytes_sent),
                )
            )

        ros_goal_future = self._action.send_goal_async(goal, feedback_callback=on_feedback)

        def goal_ready(done: object) -> None:
            try:
                goal_handle = done.result()
                if not goal_handle.accepted:
                    set_result(
                        SendResult(
                            False,
                            error_code="GOAL_REJECTED",
                            error_message="UWB Bridge가 전송 요청을 거절했습니다.",
                        )
                    )
                    return
                ros_result_future = goal_handle.get_result_async()

                def result_ready(completed: object) -> None:
                    try:
                        message = completed.result().result
                        set_result(
                            SendResult(
                                success=bool(message.success),
                                transfer_id=str(message.transfer_id),
                                frame_ack=bool(message.uwb_frame_ack),
                                remote_saved=bool(message.peer_saved),
                                application_ack=bool(message.application_ack),
                                error_code=str(message.error_code),
                                error_message=str(message.error_message),
                            )
                        )
                    except Exception as error:
                        set_exception(error)

                ros_result_future.add_done_callback(result_ready)
            except Exception as error:
                set_exception(error)

        ros_goal_future.add_done_callback(goal_ready)
        return result_future

    def _call_service(self, client: object, request: object) -> Future[bool]:
        result: Future[bool] = Future()
        if self._closed or not client.service_is_ready():
            result.set_result(False)
            return result
        ros_future = client.call_async(request)

        def completed(done: object) -> None:
            try:
                result.set_result(bool(done.result().success))
            except Exception as error:
                result.set_exception(error)

        ros_future.add_done_callback(completed)
        return result

    def reconnect(self) -> Future[bool]:
        return self._call_service(
            self._reconnect_client, self._types["Reconnect"].Request()
        )

    def cancel_transfer(self, transfer_id: str) -> Future[bool]:
        request = self._types["CancelTransfer"].Request()
        request.transfer_id = transfer_id
        return self._call_service(self._cancel_client, request)

    def request_resend(
        self, transfer_id: str, chunk_indices: Sequence[int]
    ) -> Future[bool]:
        if not chunk_indices:
            future: Future[bool] = Future()
            future.set_result(False)
            return future
        parsed = []
        for value in chunk_indices:
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 0xFFFFFFFF:
                future = Future()
                future.set_result(False)
                return future
            parsed.append(value)
        request = self._types["RequestResend"].Request()
        request.transfer_id = transfer_id
        request.chunk_indices = parsed
        return self._call_service(self._resend_client, request)

    def acknowledge_artifact(
        self, transfer_id: str, applied: bool, error_message: str = ""
    ) -> Future[bool]:
        request = self._types["AcknowledgeArtifact"].Request()
        request.transfer_id = transfer_id
        request.applied = bool(applied)
        request.error_message = error_message
        return self._call_service(self._ack_client, request)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._executor.shutdown(timeout_sec=1.0)
        self._node.destroy_node()
        if self._context.ok():
            self._context.shutdown()
        if threading.current_thread() is not self._spin_thread:
            self._spin_thread.join(timeout=1.0)
