"""Application-facing ROS action/service adapter for the UWB bridge.

ROS imports are delayed until construction so protocol/unit tests remain
hardware-independent. This adapter only performs communication; it has no
sensor, SLAM or analysis imports.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


class UwbRosClient:
    def __init__(self, node: Any) -> None:
        try:
            from rclpy.action import ActionClient
            from uwb_interfaces.action import SendArtifact
            from uwb_interfaces.srv import AcknowledgeArtifact
        except ImportError as error:
            raise RuntimeError("ROS 2 UWB interfaces are not available") from error
        self._node = node
        self._send_type = SendArtifact
        self._ack_type = AcknowledgeArtifact
        self._send = ActionClient(node, SendArtifact, "/uwb/send_artifact")
        self._ack = node.create_client(AcknowledgeArtifact, "/uwb/acknowledge_artifact")

    def send_artifact(
        self,
        path: Path,
        *,
        artifact_type: str,
        mission_id: str,
        artifact_version: int,
        priority: int = 100,
    ) -> Mapping[str, Any]:
        goal = self._send_type.Goal()
        goal.local_file_path = str(Path(path).resolve())
        goal.artifact_type = artifact_type
        goal.mission_id = mission_id
        goal.artifact_version = artifact_version
        goal.priority = priority
        goal.sha256 = ""
        return {"goal": goal, "action_client": self._send}

    def acknowledge(
        self, transfer_id: str, *, applied: bool, error_message: str = ""
    ) -> None:
        request = self._ack_type.Request()
        request.transfer_id = transfer_id
        request.applied = applied
        request.error_message = error_message
        self._ack.call_async(request)
