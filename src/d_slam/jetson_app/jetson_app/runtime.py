"""Thin Stage 3 runtime wiring around the existing sensor/analysis providers."""

from __future__ import annotations

import threading
from typing import Any, Mapping, Sequence

from .alignment import ProvisionalMissionTransform
from .analysis import AnalysisPipeline
from .config import AppConfig
from .domain import MissionManifest, PersonCandidate, Pose2D
from .perception import OpenCvYoloPersonDetectionProvider, PersonFusionEngine
from .planning import AStarRoutePlanner, RuleBasedTeamRecommendationProvider
from .providers import MockSlamProvider, deterministic_mock_candidates
from .providers.base import ProviderMode, ProviderStatus
from .risk import RuleBasedRiskAssessmentProvider
from .ros_client.adapters import (
    AstraDepthProvider,
    RosDependencyState,
    RosMapTransformer,
    RtabmapSlamProvider,
)
from .ros_client.sensor_node import (
    RosExecutorWorker,
    SensorRosNode,
    quaternion_yaw,
    ros_stamp_to_iso,
)

try:
    from nav_msgs.msg import Odometry
except ImportError:
    Odometry = None


class RuntimeUnavailableError(RuntimeError):
    """A real Stage 3 dependency is unavailable; never implies Mock fallback."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class CandidateStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._candidates: tuple[PersonCandidate, ...] = ()

    def update(self, candidates: Sequence[PersonCandidate]) -> None:
        with self._lock:
            self._candidates = tuple(candidates)

    def snapshot(self) -> tuple[PersonCandidate, ...]:
        with self._lock:
            return self._candidates

    def reset(self) -> None:
        self.update(())


def _status(
    name: str,
    *,
    connected: bool,
    message: str,
    code: str,
    mode: str = "real",
) -> dict[str, Any]:
    return {
        "name": name,
        "mode": mode,
        "connected": bool(connected),
        "message": message,
        "code": code,
    }


def _provider_status(value: ProviderStatus, *, code: str) -> dict[str, Any]:
    mode = getattr(value.mode, "value", value.mode)
    return _status(
        value.name,
        connected=value.connected,
        message=value.message,
        code="READY" if value.connected else code,
        mode=str(mode),
    )


class Stage3SensorRosNode(SensorRosNode):
    """Add RTAB odometry heartbeat/map-pose TF without replacing SensorRosNode."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._stage3_status_lock = threading.RLock()
        self._last_odometry: Any | None = None
        self._tf_ready = False
        if Odometry is not None:
            self._odometry_subscription = self.create_subscription(
                Odometry,
                self.config.topics.odometry,
                self._on_stage3_odometry,
                10,
            )
        else:
            self._odometry_subscription = None

    def _lookup_transform(
        self, source_frame: str, target_frame: str, timestamp: str | None
    ) -> Any | None:
        transform = super()._lookup_transform(source_frame, target_frame, timestamp)
        with self._state_lock:
            camera_frame = (
                self._intrinsics.frame_id if self._intrinsics is not None else None
            )
        if (
            transform is not None
            and camera_frame
            and source_frame == camera_frame
            and target_frame == self.config.slam_map_frame
        ):
            with self._stage3_status_lock:
                self._tf_ready = True
        return transform

    def _on_stage3_odometry(self, message: Any) -> None:
        """Use RTAB odometry as liveness and TF as the authoritative map pose."""

        timestamp = ros_stamp_to_iso(message.header.stamp)
        child_frame = str(message.child_frame_id or "camera_link")
        with self._stage3_status_lock:
            self._last_odometry = message
        transform = self._lookup_transform(
            child_frame, self.config.slam_map_frame, timestamp
        )
        if transform is None or transform == "identity":
            return
        pose = Pose2D(
            float(transform.translation.x),
            float(transform.translation.y),
            quaternion_yaw(transform.rotation),
        )
        with self._state_lock:
            self._latest_pose = pose
            if not self._trajectory or self._trajectory[-1] != pose:
                self._trajectory.append(pose)
        self._update_slam()

    def component_status(self) -> Mapping[str, Mapping[str, Any]]:
        with self._state_lock:
            rgb_ready = self._last_rgb is not None
            camera_info_ready = self._intrinsics is not None
        with self._stage3_status_lock:
            odom_ready = self._last_odometry is not None
            tf_ready = self._tf_ready
        slam_state = self.slam.status()
        depth_state = self.depth.status()
        rtab_connected = bool(slam_state.connected and odom_ready)
        rtab_message = slam_state.message
        if slam_state.connected and not odom_ready:
            rtab_message = f"{rtab_message}; waiting for {self.config.topics.odometry}"
        return {
            "astra_rgb": _status(
                "Astra RGB",
                connected=rgb_ready,
                message=(
                    f"receiving {self.config.topics.rgb}"
                    if rgb_ready
                    else f"waiting for {self.config.topics.rgb}"
                ),
                code="READY" if rgb_ready else "WAITING_FOR_SENSOR",
            ),
            "astra_depth": _provider_status(
                depth_state, code="WAITING_FOR_SENSOR"
            ),
            "camera_info": _status(
                "CameraInfo",
                connected=camera_info_ready,
                message=(
                    f"receiving {self.config.topics.camera_info}"
                    if camera_info_ready
                    else f"waiting for {self.config.topics.camera_info}"
                ),
                code="READY" if camera_info_ready else "WAITING_FOR_SENSOR",
            ),
            "rtabmap": _status(
                "RTAB-Map",
                connected=rtab_connected,
                message=rtab_message,
                code="READY" if rtab_connected else "WAITING_FOR_SLAM",
                mode=str(getattr(slam_state.mode, "value", slam_state.mode)),
            ),
            "tf": _status(
                "TF camera->slam_map",
                connected=tf_ready,
                message=(
                    f"TF to {self.config.slam_map_frame} available"
                    if tf_ready
                    else f"waiting for TF to {self.config.slam_map_frame}"
                ),
                code="READY" if tf_ready else "WAITING_FOR_TF",
            ),
        }

    def reset_mission_state(self) -> None:
        super().reset_mission_state()
        with self._stage3_status_lock:
            self._last_odometry = None
            self._tf_ready = False


class Stage3Runtime:
    """Own only d_slam providers; UWB remains outside this module."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.candidates = CandidateStore()
        self.transform = ProvisionalMissionTransform(
            mode=config.mission_transform_mode,
            translation_x_m=config.mission_transform_x_m,
            translation_y_m=config.mission_transform_y_m,
            yaw_radians=config.mission_transform_yaw_radians,
        )
        self.worker: RosExecutorWorker | None = None
        self._owns_rclpy = False
        self._sensor_runtime_error = ""
        self.sensor_node: Stage3SensorRosNode | None = None
        self.detector: OpenCvYoloPersonDetectionProvider | None = None
        self.depth: AstraDepthProvider | None = None

        risk = RuleBasedRiskAssessmentProvider(
            occupied_threshold=config.occupied_threshold,
            minimum_passage_width_m=config.minimum_passage_width_m,
            disconnected_minimum_cells=config.disconnected_minimum_cells,
        )
        route = AStarRoutePlanner(
            occupied_threshold=config.occupied_threshold,
            allow_unknown=config.allow_unknown_routes,
            unknown_cost=config.unknown_route_cost,
        )
        teams = RuleBasedTeamRecommendationProvider()

        if config.mode == "mock":
            self.slam = MockSlamProvider()
            self.pipeline = AnalysisPipeline(
                slam=self.slam,
                risk=risk,
                route=route,
                teams=teams,
                mission_transform=self.transform,
                confirmation_observations=config.confirmation_observations,
            )
            return

        dependencies = RosDependencyState.detect()
        self.dependencies = dependencies
        self.slam = RtabmapSlamProvider(dependencies)
        self.depth = AstraDepthProvider(
            minimum_depth_m=config.depth_minimum_m,
            maximum_depth_m=config.depth_maximum_m,
            dependency_state=dependencies,
            maximum_sync_age_s=config.sensor_sync_tolerance_s,
        )
        self.detector = OpenCvYoloPersonDetectionProvider(
            config.model_path,
            confidence_threshold=config.detection_confidence,
        )
        if dependencies.rclpy and dependencies.sensor_msgs and dependencies.nav_msgs:
            try:
                import rclpy

                if not rclpy.ok():
                    rclpy.init(args=None)
                    self._owns_rclpy = True
                self.sensor_node = Stage3SensorRosNode(
                    config,
                    self.slam,
                    self.depth,
                    candidate_callback=self.candidates.update,
                )
                transformer = RosMapTransformer(
                    self.sensor_node.camera_to_map,
                    target_frame=config.slam_map_frame,
                )
                self.sensor_node.fusion = PersonFusionEngine(
                    self.detector, self.depth, transformer
                )
                self.worker = RosExecutorWorker(self.sensor_node)
            except Exception as error:
                # API must remain inspectable on hosts/CI without a usable ROS context.
                # This is an explicit unavailable state, never a Mock fallback.
                self._sensor_runtime_error = str(error)
                self.sensor_node = None
                self.worker = None
        self.pipeline = AnalysisPipeline(
            slam=self.slam,
            risk=risk,
            route=route,
            teams=teams,
            mission_transform=self.transform,
            confirmation_observations=config.confirmation_observations,
        )

    def start(self) -> None:
        if self.worker is not None:
            self.worker.start()

    def stop(self) -> None:
        if self.worker is not None:
            self.worker.stop()
        if self._owns_rclpy:
            try:
                import rclpy

                if rclpy.ok():
                    rclpy.shutdown()
            finally:
                self._owns_rclpy = False

    def reset_mission(self) -> None:
        self.candidates.reset()
        self.transform.reset()
        if self.sensor_node is not None:
            self.sensor_node.reset_mission_state()

    def candidate_source(self) -> tuple[PersonCandidate, ...]:
        if self.config.mode == "mock":
            return deterministic_mock_candidates()
        return self.candidates.snapshot()

    def _real_component_status(self) -> dict[str, Mapping[str, Any]]:
        if self.sensor_node is not None:
            sensors = dict(self.sensor_node.component_status())
        else:
            slam_state = self.slam.status()
            depth_state = self.depth.status() if self.depth is not None else None
            sensors = {
                "astra_rgb": _status(
                    "Astra RGB",
                    connected=False,
                    message=self._sensor_runtime_error or "ROS sensor runtime is unavailable",
                    code="WAITING_FOR_SENSOR",
                ),
                "astra_depth": (
                    _provider_status(depth_state, code="WAITING_FOR_SENSOR")
                    if depth_state is not None
                    else _status(
                        "Astra depth",
                        connected=False,
                        message="ROS sensor runtime is unavailable",
                        code="WAITING_FOR_SENSOR",
                    )
                ),
                "camera_info": _status(
                    "CameraInfo",
                    connected=False,
                    message=self._sensor_runtime_error or "ROS sensor runtime is unavailable",
                    code="WAITING_FOR_SENSOR",
                ),
                "rtabmap": _provider_status(slam_state, code="WAITING_FOR_SLAM"),
                "tf": _status(
                    "TF camera->slam_map",
                    connected=False,
                    message=self._sensor_runtime_error or "ROS TF runtime is unavailable",
                    code="WAITING_FOR_TF",
                ),
            }
        detector_state = (
            self.detector.status()
            if self.detector is not None
            else ProviderStatus(
                "OpenCV ONNX person detector",
                ProviderMode.UNAVAILABLE,
                False,
                "detector is not configured",
            )
        )
        detector_code = (
            "MODEL_NOT_CONFIGURED"
            if self.config.model_path is None
            else "YOLO_UNAVAILABLE"
        )
        detector_status = _provider_status(detector_state, code=detector_code)
        if (
            detector_status["connected"]
            and getattr(self, "dependencies", None) is not None
            and not self.dependencies.cv_bridge
        ):
            detector_status = _status(
                "OpenCV ONNX person detector",
                connected=False,
                message="cv_bridge is required to decode production ROS RGB frames",
                code="YOLO_UNAVAILABLE",
                mode="unavailable",
            )
        sensors["yolo_model"] = detector_status
        sensors["analysis_mode"] = _status(
            "Analysis mode",
            connected=True,
            message="real sensor analysis; no automatic Mock fallback",
            code="READY",
            mode="real",
        )
        return sensors

    def component_status(self) -> Mapping[str, Mapping[str, Any]]:
        if self.config.mode == "mock":
            return {
                "analysis_mode": _status(
                    "Analysis mode",
                    connected=True,
                    message="explicit Mock mode",
                    code="READY",
                    mode="mock",
                )
            }
        return self._real_component_status()

    def ensure_analysis_ready(self) -> None:
        if self.config.mode == "mock":
            return
        statuses = self._real_component_status()
        order = (
            "yolo_model",
            "astra_rgb",
            "astra_depth",
            "camera_info",
            "rtabmap",
            "tf",
        )
        for key in order:
            value = statuses[key]
            if not value["connected"]:
                raise RuntimeUnavailableError(str(value["code"]), str(value["message"]))

    def map_alignment_for(self, mission: MissionManifest) -> Mapping[str, Any] | None:
        try:
            snapshot = self.slam.snapshot()
        except Exception:
            return None
        slam_start_pose = (
            snapshot.trajectory[0] if snapshot.trajectory else snapshot.robot_pose
        )
        transform = (
            ProvisionalMissionTransform.identity_for_mock()
            if self.config.mode == "mock"
            else self.transform.resolve(mission, slam_start_pose)
        )
        return transform.metadata()



__all__ = [
    "CandidateStore",
    "RuntimeUnavailableError",
    "Stage3Runtime",
    "Stage3SensorRosNode",
]
