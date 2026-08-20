"""Optional ROS 2/standalone adapter around the Stage 2 UWB core.

ROS and pyserial remain delayed imports.  Stage 5 adds only the reconnectable
serial lifecycle; packet/chunk/SHA/ACK/NACK/spool behavior stays in the existing
:mod:`ai_rescue_uwb_common` protocol and bridge modules.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Sequence

from .bridge import ArtifactBridgeCore, BridgeEvent, BridgeEventKind, TransferResult
from .managed_serial import ManagedSerialTransport, SerialTransportStatus
from .protocol import (
    DEFAULT_MAX_ARTIFACT_BYTES,
    ArtifactMetadata,
    ProtocolError,
    generate_transfer_id,
)
from .spool import SpoolError, SpoolManager
from .transport import TransportError, create_memory_link


DEFAULT_BAUDRATE = 460800
RECEIVED_ARTIFACT_QOS_DEPTH = 64
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _transient_artifact_qos(
    qos_profile_type: type, reliability_policy: object, durability_policy: object
) -> object:
    profile = qos_profile_type(depth=RECEIVED_ARTIFACT_QOS_DEPTH)
    profile.reliability = reliability_policy.RELIABLE
    profile.durability = durability_policy.TRANSIENT_LOCAL
    return profile


def validate_goal_sha256(requested: object, actual: str) -> None:
    if not isinstance(requested, str) or SHA256_RE.fullmatch(requested) is None:
        raise ProtocolError("goal SHA-256 must be 64 lowercase hex characters")
    if requested != actual:
        raise ProtocolError("goal SHA-256 differs from the local file")


def build_argument_parser(role: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=f"uwb_{role}_bridge",
        description=f"AI Rescue Box {role.title()} UWB bridge",
    )
    parser.add_argument(
        "--port",
        default=os.environ.get(
            "AI_RESCUE_UWB_SERIAL_PORT", os.environ.get("AI_RESCUE_UWB_PORT", "")
        ),
        help="ESP32 serial port; blank starts in disconnected/unconfigured state",
    )
    parser.add_argument(
        "--baudrate",
        "--baud",
        dest="baudrate",
        type=int,
        default=int(
            os.environ.get(
                "AI_RESCUE_UWB_BAUD",
                os.environ.get("AI_RESCUE_UWB_BAUDRATE", DEFAULT_BAUDRATE),
            )
        ),
        help=f"USB serial baud rate (default: {DEFAULT_BAUDRATE})",
    )
    parser.add_argument(
        "--spool-dir",
        type=Path,
        default=Path(os.environ.get("AI_RESCUE_UWB_SPOOL", "data/uwb_spool")),
        help="spool root containing outgoing/incoming/completed/failed",
    )
    parser.add_argument(
        "--auto-discover",
        action="store_true",
        default=_env_bool("AI_RESCUE_UWB_AUTO_DISCOVER", False),
        help="select a port only when exactly one serial candidate is present",
    )
    parser.add_argument(
        "--no-ros",
        action="store_true",
        help="run the serial bridge without ROS 2 (diagnostic mode)",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="run a mock transfer without ROS, serial, radio or hardware",
    )
    parser.add_argument("--send-artifact", type=Path, help="diagnostic file to send")
    parser.add_argument(
        "--artifact-type", default="mission_manifest", help="type for --send-artifact"
    )
    parser.add_argument("--mission-id", default="diagnostic")
    parser.add_argument("--artifact-version", type=int, default=1)
    parser.add_argument("--priority", type=int, default=100)
    parser.add_argument(
        "--max-artifact-bytes", type=int, default=DEFAULT_MAX_ARTIFACT_BYTES
    )
    parser.add_argument("--firmware-ack-timeout", type=float, default=2.0)
    parser.add_argument("--firmware-max-attempts", type=int, default=3)
    parser.add_argument("--stored-ack-timeout", type=float, default=5.0)
    parser.add_argument("--application-ack-timeout", type=float, default=30.0)
    parser.add_argument("--max-repair-rounds", type=int, default=4)
    parser.add_argument("--abandoned-part-age-seconds", type=float, default=3600.0)
    parser.add_argument("--serial-send-timeout", type=float, default=20.0)
    parser.add_argument(
        "--send-queue-limit",
        type=int,
        default=int(os.environ.get("AI_RESCUE_UWB_SEND_QUEUE_LIMIT", "32")),
    )
    parser.add_argument("--reconnect-initial-delay", type=float, default=0.25)
    parser.add_argument("--reconnect-max-delay", type=float, default=3.0)
    parser.add_argument("--reconnect-attempts", type=int, default=6)
    parser.add_argument("--reconnect-cooldown", type=float, default=5.0)
    parser.add_argument(
        "--no-application-ack",
        action="store_true",
        help="diagnostic send waits only for peer bridge storage",
    )
    parser.add_argument(
        "--auto-apply-ack",
        action="store_true",
        help="diagnostic receiver ACKs application apply immediately",
    )
    return parser


def _print_event(event: BridgeEvent) -> None:
    if event.kind in {BridgeEventKind.TX_PROGRESS, BridgeEventKind.RX_PROGRESS}:
        if event.completed_chunks == event.total_chunks or event.completed_chunks % 100 == 0:
            print(
                f"[{event.kind.value}] {event.transfer_id} "
                f"{event.completed_chunks}/{event.total_chunks}"
            )
        return
    message = f" {event.message}" if event.message else ""
    print(f"[{event.kind.value}] {event.transfer_id}{message}".rstrip())


def run_self_test(role: str) -> int:
    with tempfile.TemporaryDirectory(prefix="ai-rescue-uwb-check-") as directory:
        root = Path(directory)
        source = root / "mission.json"
        source.write_text('{"mission_id":"self-test","ok":true}\n', encoding="utf-8")
        host_transport, jetson_transport = create_memory_link()
        host = ArtifactBridgeCore(
            "host",
            SpoolManager(root / "host_spool"),
            host_transport,
            stored_ack_timeout=1.0,
            application_ack_timeout=1.0,
        )
        jetson: ArtifactBridgeCore

        def on_jetson_event(event: BridgeEvent) -> None:
            if event.kind is BridgeEventKind.RECEIVED:
                jetson.acknowledge_applied(event.transfer_id)

        jetson = ArtifactBridgeCore(
            "jetson",
            SpoolManager(root / "jetson_spool"),
            jetson_transport,
            stored_ack_timeout=1.0,
            application_ack_timeout=1.0,
            on_event=on_jetson_event,
        )
        host.start()
        jetson.start()
        try:
            metadata = ArtifactMetadata.from_file(
                source,
                artifact_type="mission_manifest",
                mission_id="self-test",
                artifact_version=1,
                sender="host",
            )
            result = host.send_artifact(source, metadata, transfer_id="1234abcd")
            received = jetson.completed_artifact("1234abcd")
            if not result.success or received is None:
                print(f"[SELF TEST FAIL] {result.error_message}", file=sys.stderr)
                return 1
            if received.path.read_bytes() != source.read_bytes():
                print("[SELF TEST FAIL] reconstructed bytes differ", file=sys.stderr)
                return 1
            print(
                "[SELF TEST PASS]\n"
                f"role={role}\n"
                "payload_limit=111 bytes\n"
                "chunk_bytes=66\n"
                "peer_storage_ack=true\n"
                "application_ack=true"
            )
            return 0
        finally:
            host.close()
            jetson.close()


def _managed_transport(args: argparse.Namespace) -> ManagedSerialTransport:
    return ManagedSerialTransport(
        str(args.port),
        baudrate=int(args.baudrate),
        ack_timeout=float(args.firmware_ack_timeout),
        firmware_max_attempts=int(args.firmware_max_attempts),
        reconnect_initial_delay=float(args.reconnect_initial_delay),
        reconnect_max_delay=float(args.reconnect_max_delay),
        reconnect_attempts=int(args.reconnect_attempts),
        reconnect_cooldown=float(args.reconnect_cooldown),
        send_timeout=float(args.serial_send_timeout),
        max_pending_sends=int(args.send_queue_limit),
        auto_discover=bool(args.auto_discover),
    )


def run_standalone(role: str, args: argparse.Namespace) -> int:
    try:
        spool = SpoolManager(args.spool_dir, max_artifact_bytes=args.max_artifact_bytes)
        spool.cleanup_abandoned_parts(
            age_seconds=args.abandoned_part_age_seconds, now=time.time
        )
        transport = _managed_transport(args)
        bridge: ArtifactBridgeCore

        def status_callback(status: SerialTransportStatus) -> None:
            port = status.active_port or status.configured_port or "<unconfigured>"
            detail = f" error={status.last_error}" if status.last_error else ""
            print(f"[SERIAL {status.state.upper()}] port={port}{detail}")

        transport.add_status_listener(status_callback)

        def event_callback(event: BridgeEvent) -> None:
            _print_event(event)
            if args.auto_apply_ack and event.kind is BridgeEventKind.RECEIVED:
                bridge.acknowledge_applied(event.transfer_id)

        bridge = ArtifactBridgeCore(
            role,
            spool,
            transport,
            stored_ack_timeout=args.stored_ack_timeout,
            application_ack_timeout=args.application_ack_timeout,
            max_repair_rounds=args.max_repair_rounds,
            on_event=event_callback,
        )
        bridge.start()
        try:
            if args.send_artifact is not None:
                metadata = ArtifactMetadata.from_file(
                    args.send_artifact,
                    artifact_type=args.artifact_type,
                    mission_id=args.mission_id,
                    artifact_version=args.artifact_version,
                    sender=role,
                    priority=args.priority,
                )
                result = bridge.send_artifact(
                    args.send_artifact,
                    metadata,
                    require_application_ack=not args.no_application_ack,
                )
                print(result)
                return 0 if result.success else 1
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            return 0
        finally:
            bridge.close()
    except (OSError, ProtocolError, SpoolError, TransportError, ValueError) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1


def run_ros(role: str, args: argparse.Namespace, ros_args: Sequence[str]) -> int:
    os.environ.setdefault("ROS_LOCALHOST_ONLY", "1")
    try:
        import rclpy
        from rclpy.action import ActionServer, CancelResponse, GoalResponse
        from rclpy.callback_groups import ReentrantCallbackGroup
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
        print(
            "[ERROR] ROS 2 Python packages or generated uwb_interfaces are unavailable. "
            "Source the ROS/colcon setup, or use --no-ros / --self-test.\n"
            f"detail: {error}",
            file=sys.stderr,
        )
        return 2

    class RosBridgeNode(Node):
        def __init__(self) -> None:
            super().__init__(f"uwb_{role}_bridge")
            self.declare_parameter("port", args.port)
            self.declare_parameter("baudrate", args.baudrate)
            self.declare_parameter("spool_dir", str(args.spool_dir))
            self.declare_parameter("stored_ack_timeout", args.stored_ack_timeout)
            self.declare_parameter("application_ack_timeout", args.application_ack_timeout)
            self.declare_parameter("max_artifact_bytes", args.max_artifact_bytes)
            self.declare_parameter("firmware_ack_timeout", args.firmware_ack_timeout)
            self.declare_parameter("firmware_max_attempts", args.firmware_max_attempts)
            self.declare_parameter("max_repair_rounds", args.max_repair_rounds)
            self.declare_parameter("abandoned_part_age_seconds", args.abandoned_part_age_seconds)
            self.declare_parameter("require_application_ack", True)
            self.declare_parameter("serial_send_timeout", args.serial_send_timeout)
            self.declare_parameter("send_queue_limit", args.send_queue_limit)
            self.declare_parameter("reconnect_initial_delay", args.reconnect_initial_delay)
            self.declare_parameter("reconnect_max_delay", args.reconnect_max_delay)
            self.declare_parameter("reconnect_attempts", args.reconnect_attempts)
            self.declare_parameter("reconnect_cooldown", args.reconnect_cooldown)
            self.declare_parameter("auto_discover", args.auto_discover)

            self._port = str(self.get_parameter("port").value)
            self._baudrate = int(self.get_parameter("baudrate").value)
            self._spool = SpoolManager(
                Path(str(self.get_parameter("spool_dir").value)),
                max_artifact_bytes=int(self.get_parameter("max_artifact_bytes").value),
            )
            moved = self._spool.cleanup_abandoned_parts(
                age_seconds=float(self.get_parameter("abandoned_part_age_seconds").value),
                now=time.time,
            )
            if moved:
                self.get_logger().warning(
                    f"moved {moved} abandoned incoming part(s) to failed"
                )
            self._transport = ManagedSerialTransport(
                self._port,
                baudrate=self._baudrate,
                ack_timeout=float(self.get_parameter("firmware_ack_timeout").value),
                firmware_max_attempts=int(
                    self.get_parameter("firmware_max_attempts").value
                ),
                reconnect_initial_delay=float(
                    self.get_parameter("reconnect_initial_delay").value
                ),
                reconnect_max_delay=float(
                    self.get_parameter("reconnect_max_delay").value
                ),
                reconnect_attempts=int(self.get_parameter("reconnect_attempts").value),
                reconnect_cooldown=float(
                    self.get_parameter("reconnect_cooldown").value
                ),
                send_timeout=float(self.get_parameter("serial_send_timeout").value),
                max_pending_sends=int(self.get_parameter("send_queue_limit").value),
                auto_discover=bool(self.get_parameter("auto_discover").value),
                status_callback=self._on_serial_status,
            )
            self._core = ArtifactBridgeCore(
                role,
                self._spool,
                self._transport,
                stored_ack_timeout=float(self.get_parameter("stored_ack_timeout").value),
                application_ack_timeout=float(
                    self.get_parameter("application_ack_timeout").value
                ),
                max_repair_rounds=int(self.get_parameter("max_repair_rounds").value),
                on_event=self._on_bridge_event,
            )
            self._core.start()
            self._callback_group = ReentrantCallbackGroup()
            self._goal_transfer_lock = threading.Lock()
            self._goal_transfers: dict[int, str] = {}
            status_qos = QoSProfile(depth=1)
            status_qos.reliability = ReliabilityPolicy.RELIABLE
            status_qos.durability = DurabilityPolicy.TRANSIENT_LOCAL
            self._status_publisher = self.create_publisher(
                UwbStatus, "/uwb/status", status_qos
            )
            received_qos = _transient_artifact_qos(
                QoSProfile, ReliabilityPolicy, DurabilityPolicy
            )
            self._received_publisher = self.create_publisher(
                ReceivedArtifact, "/uwb/received_artifact", received_qos
            )
            self._action = ActionServer(
                self,
                SendArtifact,
                "/uwb/send_artifact",
                execute_callback=self._execute_send,
                goal_callback=self._goal_callback,
                cancel_callback=self._cancel_callback,
                callback_group=self._callback_group,
            )
            self._reconnect_service = self.create_service(
                Reconnect,
                "/uwb/reconnect",
                self._reconnect,
                callback_group=self._callback_group,
            )
            self._cancel_service = self.create_service(
                CancelTransfer,
                "/uwb/cancel_transfer",
                self._cancel_transfer,
                callback_group=self._callback_group,
            )
            self._resend_service = self.create_service(
                RequestResend,
                "/uwb/request_resend",
                self._request_resend,
                callback_group=self._callback_group,
            )
            self._ack_service = self.create_service(
                AcknowledgeArtifact,
                "/uwb/acknowledge_artifact",
                self._acknowledge_artifact,
                callback_group=self._callback_group,
            )
            self._status_timer = self.create_timer(0.5, self._publish_status)

        def _on_serial_status(self, status: SerialTransportStatus) -> None:
            port = status.active_port or status.configured_port or "<unconfigured>"
            if status.connected:
                self.get_logger().info(
                    f"serial connected port={port} baud={status.baudrate}"
                )
            elif status.last_error:
                self.get_logger().warning(
                    f"serial {status.state} port={port}: {status.last_error}"
                )

        @staticmethod
        def _set_time(target: object, value: float) -> None:
            if value <= 0:
                target.sec = 0
                target.nanosec = 0
                return
            seconds = int(value)
            target.sec = seconds
            target.nanosec = int((value - seconds) * 1_000_000_000)

        def _publish_status(self) -> None:
            message = UwbStatus()
            message.role = role
            snapshot = self._core.snapshot()
            serial = self._transport.status()
            message.bridge_running = snapshot.running
            message.serial_connected = serial.connected
            message.peer_connected = snapshot.peer_connected and serial.connected
            message.transfer_state = snapshot.transfer_state
            message.transfer_id = snapshot.transfer_id
            message.bytes_sent = snapshot.bytes_sent
            message.bytes_received = snapshot.bytes_received
            message.retransmission_count = snapshot.retransmissions
            message.last_error_code = (
                snapshot.last_error_code
                if serial.connected
                else ("serial_unconfigured" if serial.state == "unconfigured" else "serial_unavailable")
            )
            message.last_error_message = serial.last_error or snapshot.last_error_message
            self._set_time(message.last_tx_time, snapshot.last_tx_time)
            self._set_time(message.last_rx_time, snapshot.last_rx_time)
            self._status_publisher.publish(message)

        def _on_bridge_event(self, event: BridgeEvent) -> None:
            if event.kind is not BridgeEventKind.RECEIVED or event.artifact is None:
                return
            artifact = event.artifact
            message = ReceivedArtifact()
            message.transfer_id = artifact.transfer_id
            message.artifact_type = artifact.metadata.artifact_type
            message.mission_id = artifact.metadata.mission_id
            message.artifact_version = artifact.metadata.artifact_version
            message.local_file_path = str(artifact.path.resolve())
            message.file_size = artifact.metadata.file_size
            message.sha256 = artifact.metadata.sha256
            message.sender = artifact.metadata.sender
            self._set_time(message.received_at, time.time())
            self._received_publisher.publish(message)
            self.get_logger().info(
                f"received transfer={artifact.transfer_id} "
                f"type={artifact.metadata.artifact_type} bytes={artifact.metadata.file_size}"
            )

        def _goal_callback(self, goal_request: object) -> object:
            del goal_request
            serial = self._transport.status()
            if serial.state == "unconfigured":
                self.get_logger().warning("rejecting send goal: serial port unconfigured")
                return GoalResponse.REJECT
            return GoalResponse.ACCEPT

        def _cancel_callback(self, goal_handle: object) -> object:
            with self._goal_transfer_lock:
                transfer_id = self._goal_transfers.get(id(goal_handle))
            if transfer_id:
                self._core.cancel_transfer(transfer_id)
            return CancelResponse.ACCEPT

        def _execute_send(self, goal_handle: object) -> object:
            result_message = SendArtifact.Result()
            request = goal_handle.request
            source = Path(request.local_file_path)
            transfer_id = generate_transfer_id()
            with self._goal_transfer_lock:
                self._goal_transfers[id(goal_handle)] = transfer_id
            try:
                if goal_handle.is_cancel_requested:
                    result_message.transfer_id = transfer_id
                    result_message.error_code = "cancelled"
                    result_message.error_message = "goal cancelled before transmission"
                    goal_handle.canceled()
                    return result_message
                metadata = ArtifactMetadata.from_file(
                    source,
                    artifact_type=request.artifact_type,
                    mission_id=request.mission_id,
                    artifact_version=int(request.artifact_version),
                    sender=role,
                    priority=int(request.priority),
                )
                validate_goal_sha256(request.sha256, metadata.sha256)
                self.get_logger().info(
                    f"send type={metadata.artifact_type} mission={metadata.mission_id} "
                    f"version={metadata.artifact_version} bytes={metadata.file_size}"
                )

                def feedback_callback(event: BridgeEvent) -> None:
                    if goal_handle.is_cancel_requested:
                        self._core.cancel_transfer(event.transfer_id)
                    feedback = SendArtifact.Feedback()
                    feedback.transfer_id = event.transfer_id
                    feedback.stage = event.message or self._core.snapshot().transfer_state
                    feedback.total_chunks = event.total_chunks
                    feedback.completed_chunks = event.completed_chunks
                    feedback.progress = (
                        float(event.completed_chunks) / float(event.total_chunks)
                        if event.total_chunks
                        else 0.0
                    )
                    feedback.retransmission_count = event.retries
                    feedback.bytes_sent = event.bytes_sent
                    goal_handle.publish_feedback(feedback)

                outcome = self._core.send_artifact(
                    source,
                    metadata,
                    transfer_id=transfer_id,
                    require_application_ack=(
                        bool(self.get_parameter("require_application_ack").value)
                        and request.artifact_type != "base_map"
                    ),
                    progress=feedback_callback,
                )
            except Exception as error:
                outcome = TransferResult(
                    False,
                    transfer_id,
                    False,
                    False,
                    False,
                    type(error).__name__.lower(),
                    str(error),
                )
            finally:
                with self._goal_transfer_lock:
                    self._goal_transfers.pop(id(goal_handle), None)
            result_message.success = outcome.success
            result_message.transfer_id = outcome.transfer_id
            result_message.uwb_frame_ack = outcome.uwb_frame_ack
            result_message.peer_saved = outcome.peer_saved
            result_message.application_ack = outcome.application_ack
            result_message.error_code = outcome.error_code
            result_message.error_message = outcome.error_message
            if outcome.success:
                goal_handle.succeed()
            elif goal_handle.is_cancel_requested:
                goal_handle.canceled()
            else:
                goal_handle.abort()
            self.get_logger().info(
                f"send result transfer={outcome.transfer_id} success={outcome.success} "
                f"frame_ack={outcome.uwb_frame_ack} peer_stored={outcome.peer_saved} "
                f"application_ack={outcome.application_ack} retries={outcome.retries}"
            )
            return result_message

        def _reconnect(self, request: object, response: object) -> object:
            del request
            self._transport.request_reconnect()
            response.success = True
            response.message = "serial reconnect cycle requested"
            return response

        def _cancel_transfer(self, request: object, response: object) -> object:
            response.success = self._core.cancel_transfer(request.transfer_id)
            response.message = "cancel requested" if response.success else "transfer not found"
            return response

        def _request_resend(self, request: object, response: object) -> object:
            try:
                self._core.request_resend(
                    request.transfer_id, tuple(int(value) for value in request.chunk_indices)
                )
                response.success = True
                response.message = "resend requested"
            except Exception as error:
                response.success = False
                response.message = str(error)
            return response

        def _acknowledge_artifact(self, request: object, response: object) -> object:
            try:
                if request.applied:
                    self._core.acknowledge_applied(request.transfer_id)
                else:
                    self._core.reject_applied(request.transfer_id, request.error_message)
                response.success = True
                response.message = "application result sent"
            except Exception as error:
                response.success = False
                response.message = str(error)
            return response

        def destroy_node(self) -> bool:
            self._transport.remove_status_listener(self._on_serial_status)
            self._core.close()
            self._action.destroy()
            return super().destroy_node()

    rclpy.init(args=list(ros_args))
    node = RosBridgeNode()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()
    return 0


def main_for_role(role: str, argv: Sequence[str] | None = None) -> int:
    parser = build_argument_parser(role)
    args, remaining = parser.parse_known_args(argv)
    if role not in {"host", "jetson"}:
        parser.error("role must be host or jetson")
    if args.baudrate <= 0:
        parser.error("--baudrate must be positive")
    if not 0 <= args.priority <= 255:
        parser.error("--priority must be between 0 and 255")
    if not 1 <= args.max_artifact_bytes <= DEFAULT_MAX_ARTIFACT_BYTES:
        parser.error(
            f"--max-artifact-bytes must be 1..{DEFAULT_MAX_ARTIFACT_BYTES}"
        )
    positive_values = {
        "--firmware-ack-timeout": args.firmware_ack_timeout,
        "--firmware-max-attempts": args.firmware_max_attempts,
        "--stored-ack-timeout": args.stored_ack_timeout,
        "--application-ack-timeout": args.application_ack_timeout,
        "--serial-send-timeout": args.serial_send_timeout,
        "--reconnect-initial-delay": args.reconnect_initial_delay,
        "--reconnect-max-delay": args.reconnect_max_delay,
        "--reconnect-attempts": args.reconnect_attempts,
        "--reconnect-cooldown": args.reconnect_cooldown,
    }
    for name, value in positive_values.items():
        if value <= 0:
            parser.error(f"{name} must be positive")
    if args.send_queue_limit <= 0:
        parser.error("--send-queue-limit must be positive")
    if args.reconnect_max_delay < args.reconnect_initial_delay:
        parser.error("--reconnect-max-delay must be >= --reconnect-initial-delay")
    if args.max_repair_rounds < 0:
        parser.error("--max-repair-rounds must be non-negative")
    if args.abandoned_part_age_seconds < 0:
        parser.error("--abandoned-part-age-seconds must be non-negative")
    if args.self_test:
        return run_self_test(role)
    if args.no_ros:
        return run_standalone(role, args)
    return run_ros(role, args, remaining)
