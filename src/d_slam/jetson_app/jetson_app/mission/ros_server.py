"""ROS 2 services exposing the existing d_slam MissionManager boundary."""
from __future__ import annotations

import os
from pathlib import Path

from .application import MissionApplicationService
from .manager import MissionManager


def main() -> int:
    try:
        import rclpy
        from ai_rescue_interfaces.srv import ApplyApprovedPlan, LoadMission
        from rclpy.callback_groups import ReentrantCallbackGroup
        from rclpy.executors import MultiThreadedExecutor
        from rclpy.node import Node
    except ImportError as error:
        raise RuntimeError(
            "ROS 2 or generated ai_rescue_interfaces are unavailable"
        ) from error

    root = Path(os.environ.get("AI_RESCUE_DATA_ROOT", "data")) / "missions"

    class MissionApplicationNode(Node):
        def __init__(self) -> None:
            super().__init__("ai_rescue_d_slam_mission_application")
            self._service = MissionApplicationService(MissionManager(root))
            group = ReentrantCallbackGroup()
            self._load = self.create_service(
                LoadMission,
                "/d_slam/load_mission",
                self._load_mission,
                callback_group=group,
            )
            self._plan = self.create_service(
                ApplyApprovedPlan,
                "/d_slam/apply_approved_plan",
                self._apply_plan,
                callback_group=group,
            )

        def _load_mission(self, request: object, response: object) -> object:
            result = self._service.load_mission(
                mission_id=str(request.mission_id),
                mission_version=int(request.mission_version),
                base_map_path=Path(str(request.base_map_path)),
                mission_manifest_path=Path(str(request.mission_manifest_path)),
            )
            response.success = result.success
            response.state = result.state
            response.error_code = result.error_code
            response.message = result.message
            return response

        def _apply_plan(self, request: object, response: object) -> object:
            result = self._service.apply_approved_plan(
                mission_id=str(request.mission_id),
                mission_version=int(request.mission_version),
                approved_plan_version=int(request.approved_plan_version),
                approved_plan_path=Path(str(request.approved_plan_path)),
            )
            response.success = result.success
            response.state = result.state
            response.error_code = result.error_code
            response.message = result.message
            return response

    rclpy.init()
    node = MissionApplicationNode()
    executor = MultiThreadedExecutor(num_threads=2)
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
