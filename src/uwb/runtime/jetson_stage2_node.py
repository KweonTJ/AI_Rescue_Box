"""ROS 2 process joining the UWB bridge to d_slam for Stage 2.

It owns the Jetson disk-backed semantic outbox. Existing SubmitRescueUpdate
remains as a diagnostic/manual compatibility path.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any, Mapping

from .mission_artifacts import ReceivedMissionArtifact
from .stage2 import ApplicationResult, JetsonStage2Runtime


def _await_future(future: Any, timeout: float, label: str) -> Any:
    event = threading.Event()
    box: dict[str, Any] = {}
    def done(completed: Any) -> None:
        try:
            box["result"] = completed.result()
        except Exception as error:
            box["error"] = error
        event.set()
    future.add_done_callback(done)
    if not event.wait(timeout):
        raise TimeoutError(f"{label} timed out")
    if "error" in box:
        raise box["error"]
    return box.get("result")


def main() -> int:
    os.environ.setdefault("ROS_LOCALHOST_ONLY", "1")
    try:
        import rclpy
        from ai_rescue_interfaces.action import SubmitRescueUpdate
        from ai_rescue_interfaces.srv import ApplyApprovedPlan, LoadMission
        from rclpy.action import ActionClient, ActionServer, GoalResponse
        from rclpy.callback_groups import ReentrantCallbackGroup
        from rclpy.executors import MultiThreadedExecutor
        from rclpy.node import Node
        from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
        from uwb_interfaces.action import SendArtifact
        from uwb_interfaces.msg import ReceivedArtifact
        from uwb_interfaces.srv import AcknowledgeArtifact
    except ImportError as error:
        raise RuntimeError("ROS 2, uwb_interfaces, or ai_rescue_interfaces are unavailable") from error

    class RosPorts:
        def __init__(self, node: Any, group: Any) -> None:
            self.SendArtifact = SendArtifact
            self.AcknowledgeArtifact = AcknowledgeArtifact
            self.LoadMission = LoadMission
            self.ApplyApprovedPlan = ApplyApprovedPlan
            self.send_client = ActionClient(node, SendArtifact, "/uwb/send_artifact", callback_group=group)
            self.ack_client = node.create_client(AcknowledgeArtifact, "/uwb/acknowledge_artifact", callback_group=group)
            self.load_client = node.create_client(LoadMission, "/d_slam/load_mission", callback_group=group)
            self.plan_client = node.create_client(ApplyApprovedPlan, "/d_slam/apply_approved_plan", callback_group=group)

        def acknowledge(self, transfer_id: str, *, applied: bool, error_message: str = "") -> None:
            if not self.ack_client.wait_for_service(timeout_sec=2.0):
                raise RuntimeError("/uwb/acknowledge_artifact is unavailable")
            request = self.AcknowledgeArtifact.Request()
            request.transfer_id = transfer_id
            request.applied = bool(applied)
            request.error_message = error_message
            response = _await_future(self.ack_client.call_async(request), 5.0, "application ACK")
            if not response.success:
                raise RuntimeError(str(response.message))

        def load_mission(self, *, mission_id: str, mission_version: int, base_map_path: Path, mission_manifest_path: Path) -> ApplicationResult:
            if not self.load_client.wait_for_service(timeout_sec=2.0):
                return ApplicationResult(False, "REJECTED", "SERVICE_UNAVAILABLE", "/d_slam/load_mission is unavailable")
            request = self.LoadMission.Request()
            request.mission_id = mission_id
            request.mission_version = int(mission_version)
            request.base_map_path = str(Path(base_map_path).resolve())
            request.mission_manifest_path = str(Path(mission_manifest_path).resolve())
            try:
                response = _await_future(self.load_client.call_async(request), 30.0, "LoadMission")
            except Exception as error:
                return ApplicationResult(False, "REJECTED", type(error).__name__.upper(), str(error))
            return ApplicationResult(bool(response.success), str(response.state), str(response.error_code), str(response.message))

        def apply_approved_plan(self, *, mission_id: str, mission_version: int, approved_plan_version: int, approved_plan_path: Path) -> ApplicationResult:
            if not self.plan_client.wait_for_service(timeout_sec=2.0):
                return ApplicationResult(False, "REJECTED", "SERVICE_UNAVAILABLE", "/d_slam/apply_approved_plan is unavailable")
            request = self.ApplyApprovedPlan.Request()
            request.mission_id = mission_id
            request.mission_version = int(mission_version)
            request.approved_plan_version = int(approved_plan_version)
            request.approved_plan_path = str(Path(approved_plan_path).resolve())
            try:
                response = _await_future(self.plan_client.call_async(request), 30.0, "ApplyApprovedPlan")
            except Exception as error:
                return ApplicationResult(False, "REJECTED", type(error).__name__.upper(), str(error))
            return ApplicationResult(bool(response.success), str(response.state), str(response.error_code), str(response.message))

        def send_artifact(self, path: Path, *, artifact_type: str, mission_id: str, artifact_version: int, priority: int = 100) -> Mapping[str, Any]:
            source = Path(path).resolve()
            if not self.send_client.wait_for_server(timeout_sec=2.0):
                raise RuntimeError("/uwb/send_artifact is unavailable")
            goal = self.SendArtifact.Goal()
            goal.local_file_path = str(source)
            goal.artifact_type = artifact_type
            goal.mission_id = mission_id
            goal.artifact_version = int(artifact_version)
            goal.priority = int(priority)
            goal.sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
            handle = _await_future(self.send_client.send_goal_async(goal), 5.0, f"{artifact_type} goal")
            if not handle.accepted:
                raise RuntimeError(f"{artifact_type} send goal was rejected")
            wrapped = _await_future(handle.get_result_async(), 45.0, f"{artifact_type} transfer")
            result = wrapped.result
            value = {
                "success": bool(result.success),
                "state": "completed" if result.success else "failed",
                "transfer_id": str(result.transfer_id),
                "frame_ack": bool(result.uwb_frame_ack),
                "peer_stored_ack": bool(result.peer_saved),
                "application_applied_ack": bool(result.application_ack),
                "error_code": str(result.error_code),
                "error_message": str(result.error_message),
            }
            if not value["success"]:
                raise RuntimeError(value["error_message"] or value["error_code"])
            return value

    class Stage2Node(Node):
        def __init__(self) -> None:
            super().__init__("ai_rescue_jetson_stage2_runtime")
            group = ReentrantCallbackGroup()
            self._ports = RosPorts(self, group)
            data_root = Path(os.environ.get("AI_RESCUE_DATA_ROOT", "data")).expanduser()
            self._runtime = JetsonStage2Runtime(
                self._ports, self._ports, self._ports, outbox_root=data_root / "uwb_outbox"
            )
            qos = QoSProfile(depth=64)
            qos.reliability = ReliabilityPolicy.RELIABLE
            qos.durability = DurabilityPolicy.TRANSIENT_LOCAL
            self._subscription = self.create_subscription(
                ReceivedArtifact, "/uwb/received_artifact", self._received, qos, callback_group=group
            )
            self._submit = ActionServer(
                self, SubmitRescueUpdate, "/uwb/submit_rescue_update",
                execute_callback=self._submit_update,
                goal_callback=lambda _: GoalResponse.ACCEPT,
                callback_group=group,
            )
            self._queue = ActionServer(
                self, SendArtifact, "/uwb/queue_artifact",
                execute_callback=self._queue_artifact,
                goal_callback=lambda _: GoalResponse.ACCEPT,
                callback_group=group,
            )
            interval = float(os.environ.get("AI_RESCUE_UWB_OUTBOX_DRAIN_SECONDS", "1.0"))
            self._drain_timer = self.create_timer(max(0.2, interval), self._drain_outbox, callback_group=group)

        def _received(self, message: object) -> None:
            artifact = ReceivedMissionArtifact(
                transfer_id=str(message.transfer_id),
                artifact_type=str(message.artifact_type),
                mission_id=str(message.mission_id),
                artifact_version=int(message.artifact_version),
                local_file_path=Path(str(message.local_file_path)),
                sha256=str(message.sha256),
            )
            state = self._runtime.handle_received(artifact)
            self.get_logger().info(f"Stage 2 receive {artifact.artifact_type} {artifact.transfer_id}: {state}")

        def _queue_artifact(self, goal_handle: object) -> object:
            request = goal_handle.request
            result_message = SendArtifact.Result()
            try:
                source = Path(str(request.local_file_path)).resolve()
                if not source.is_file():
                    raise ValueError("queued artifact path does not exist")
                digest = hashlib.sha256(source.read_bytes()).hexdigest()
                if str(request.sha256) != digest:
                    raise ValueError("queued artifact SHA-256 differs from request")
                outcome = dict(self._runtime.queue_artifact(
                    source,
                    artifact_type=str(request.artifact_type),
                    mission_id=str(request.mission_id),
                    artifact_version=int(request.artifact_version),
                    priority=int(request.priority),
                ))
                result_message.success = True
                result_message.transfer_id = str(outcome.get("transfer_id") or outcome.get("entry_id") or "")
                result_message.uwb_frame_ack = bool(outcome.get("frame_ack", False))
                result_message.peer_saved = bool(outcome.get("peer_stored_ack", False))
                result_message.application_ack = bool(outcome.get("application_applied_ack", outcome.get("application_ack", False)))
                result_message.error_code = str(outcome.get("error_code", ""))
                result_message.error_message = str(outcome.get("error_message", ""))
                goal_handle.succeed()
            except Exception as error:
                result_message.success = False
                result_message.transfer_id = ""
                result_message.uwb_frame_ack = False
                result_message.peer_saved = False
                result_message.application_ack = False
                result_message.error_code = type(error).__name__.lower()
                result_message.error_message = str(error)
                goal_handle.abort()
            return result_message

        def _drain_outbox(self) -> None:
            for outcome in self._runtime.drain_outbox(max_entries=8):
                if outcome.get("error_message") and not (outcome.get("application_applied_ack") or outcome.get("application_ack")):
                    self.get_logger().warning(
                        f"outbox pending entry={outcome.get('entry_id')}: {outcome.get('error_message')}"
                    )

        def _submit_update(self, goal_handle: object) -> object:
            result_message = SubmitRescueUpdate.Result()
            request = goal_handle.request
            semantic = Path(str(request.semantic_result_path)).resolve()
            try:
                payload = json.loads(semantic.read_text(encoding="utf-8"))
                if str(payload.get("mission_id")) != str(request.mission_id):
                    raise ValueError("SubmitRescueUpdate mission_id does not match semantic_result")
                if int(payload.get("base_map_version", 0)) != int(request.mission_version):
                    raise ValueError("SubmitRescueUpdate mission_version does not match semantic_result")
                if int(payload.get("result_version", 0)) != int(request.result_version):
                    raise ValueError("SubmitRescueUpdate result_version does not match semantic_result")
                preview = semantic.parent / "map_preview.png"
                if not preview.is_file():
                    raise ValueError("map_preview.png is not stored beside semantic_result")
                first, second = self._runtime.return_analysis(semantic, preview)
                result_message.accepted = True
                result_message.transfer_id = (
                    f"{first.get('transfer_id', first.get('entry_id',''))}:"
                    f"{second.get('transfer_id', second.get('entry_id',''))}"
                )
                result_message.message = "semantic_result and map_preview persisted to UWB outbox"
                goal_handle.succeed()
            except Exception as error:
                result_message.accepted = False
                result_message.transfer_id = ""
                result_message.message = str(error)
                goal_handle.abort()
            return result_message

    rclpy.init()
    node = Stage2Node()
    executor = MultiThreadedExecutor(num_threads=6)
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


if __name__ == "__main__":
    raise SystemExit(main())
