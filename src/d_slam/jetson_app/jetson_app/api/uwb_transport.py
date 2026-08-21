"""d_slam adapter to the public UWB durable queue action."""
from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from typing import Any, Mapping


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


class RosUwbArtifactTransport:
    """Submit Jetson artifacts to ``/uwb/queue_artifact`` for durable delivery."""

    def __init__(self, node: Any, *, timeout: float = 10.0) -> None:
        try:
            from rclpy.action import ActionClient
            from uwb_interfaces.action import SendArtifact
        except ImportError as error:
            raise RuntimeError("ROS 2 uwb_interfaces are unavailable") from error
        self._client = ActionClient(node, SendArtifact, "/uwb/queue_artifact")
        self._SendArtifact = SendArtifact
        self._timeout = float(timeout)

    def status(self) -> Mapping[str, Any]:
        ready = bool(self._client.server_is_ready())
        return {
            "name": "UWB persistent semantic queue",
            "mode": "ros_action",
            "connected": ready,
            "message": "/uwb/queue_artifact ready" if ready else "/uwb/queue_artifact unavailable; no silent mock fallback",
        }

    def _send(self, path: Path, *, artifact_type: str, mission_id: str, artifact_version: int, priority: int) -> Mapping[str, Any]:
        source = Path(path).expanduser().resolve()
        if not source.is_file():
            raise RuntimeError(f"artifact does not exist: {source}")
        if not self._client.wait_for_server(timeout_sec=min(2.0, self._timeout)):
            raise RuntimeError("/uwb/queue_artifact is unavailable")
        goal = self._SendArtifact.Goal()
        goal.local_file_path = str(source)
        goal.artifact_type = str(artifact_type)
        goal.mission_id = str(mission_id)
        goal.artifact_version = int(artifact_version)
        goal.priority = int(priority)
        goal.sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
        handle = _await_future(self._client.send_goal_async(goal), self._timeout, f"queue {artifact_type} goal")
        if not handle.accepted:
            raise RuntimeError(f"{artifact_type} durable queue goal was rejected")
        wrapped = _await_future(handle.get_result_async(), self._timeout, f"queue {artifact_type} result")
        result = wrapped.result
        if not bool(result.success):
            raise RuntimeError(str(result.error_message or result.error_code))
        return {
            "success": True,
            "state": "persisted",
            "transfer_id": str(result.transfer_id),
            "frame_ack": bool(result.uwb_frame_ack),
            "peer_stored_ack": bool(result.peer_saved),
            "application_applied_ack": bool(result.application_ack),
            "error_code": str(result.error_code),
            "error_message": str(result.error_message),
        }

    def send_semantic_result(self, result: Mapping[str, Any], path: Path, *, priority: int = 0) -> Mapping[str, Any]:
        return self._send(path, artifact_type="semantic_result", mission_id=str(result["mission_id"]), artifact_version=int(result["result_version"]), priority=priority)

    def send_map_delta(self, delta: Mapping[str, Any], path: Path, *, priority: int = 0) -> Mapping[str, Any]:
        return self._send(path, artifact_type="map_delta", mission_id=str(delta["mission_id"]), artifact_version=int(delta["result_version"]), priority=priority)

    def send_urgent_event(self, event: Mapping[str, Any], path: Path, *, priority: int = 0) -> Mapping[str, Any]:
        return self._send(path, artifact_type="urgent_event", mission_id=str(event["mission_id"]), artifact_version=int(event["artifact_version"]), priority=max(priority, int(event.get("priority", 0))))

    def send_map_preview(self, metadata: Mapping[str, Any], path: Path, *, priority: int = 0) -> Mapping[str, Any]:
        return self._send(path, artifact_type="map_preview", mission_id=str(metadata["mission_id"]), artifact_version=int(metadata["artifact_version"]), priority=priority)

    def send_mission_state(self, state: Mapping[str, Any], path: Path, *, priority: int = 0) -> Mapping[str, Any]:
        """Persist a tiny ACTIVE Mission metadata snapshot in the UWB outbox."""
        return self._send(
            path,
            artifact_type="mission_state",
            mission_id=str(state["mission_id"]),
            artifact_version=int(state["artifact_version"]),
            priority=max(priority, 180),
        )


__all__ = ["RosUwbArtifactTransport"]
