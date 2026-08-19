"""ROS data adapter points for Astra Depth, TF and RTAB-Map.

The classes accept already-decoded data through update methods. A ROS node can
subscribe on configurable topics and feed them here without coupling planning
logic to rclpy. Missing ROS packages produce an unavailable status, never Mock.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from datetime import datetime
from importlib.util import find_spec
from typing import Callable, Sequence

from ..domain import CameraPoint, OccupancyGrid, Point2D, Pose2D
from ..providers.base import (
    CameraIntrinsics,
    DependencyUnavailableError,
    DepthProvider,
    Detection2D,
    MapTransformer,
    ProviderMode,
    ProviderStatus,
    SlamProvider,
    SlamSnapshot,
)


@dataclass(frozen=True)
class RosDependencyState:
    rclpy: bool
    sensor_msgs: bool
    nav_msgs: bool
    tf2_ros: bool
    cv_bridge: bool
    rtabmap_msgs: bool
    astra_camera: bool

    @classmethod
    def detect(cls) -> "RosDependencyState":
        available = lambda name: find_spec(name) is not None
        return cls(
            rclpy=available("rclpy"),
            sensor_msgs=available("sensor_msgs"),
            nav_msgs=available("nav_msgs"),
            tf2_ros=available("tf2_ros"),
            cv_bridge=available("cv_bridge"),
            rtabmap_msgs=available("rtabmap_msgs"),
            astra_camera=available("astra_camera"),
        )


class RtabmapSlamProvider(SlamProvider):
    """Thread-safe RTAB-Map snapshot cache populated by ROS subscriptions."""

    def __init__(self, dependency_state: RosDependencyState | None = None) -> None:
        self.dependencies = dependency_state or RosDependencyState.detect()
        self._snapshot: SlamSnapshot | None = None
        self._lock = threading.RLock()

    def update(
        self,
        *,
        occupancy_grid: OccupancyGrid,
        robot_pose: Pose2D,
        trajectory: Sequence[Pose2D],
        explored_areas: Sequence[Sequence[Point2D]],
        unknown_areas: Sequence[Sequence[Point2D]],
        tracking_status: str,
        map_version: int,
        sensor_risks: Sequence = (),
    ) -> None:
        with self._lock:
            self._snapshot = SlamSnapshot(
                occupancy_grid,
                robot_pose,
                tuple(trajectory),
                tuple(tuple(area) for area in explored_areas),
                tuple(tuple(area) for area in unknown_areas),
                tracking_status,
                map_version,
                sensor_risks=tuple(sensor_risks),
            )

    def status(self) -> ProviderStatus:
        if not (self.dependencies.rclpy and self.dependencies.nav_msgs):
            return ProviderStatus(
                "RTAB-Map SLAM",
                ProviderMode.UNAVAILABLE,
                False,
                "ROS 2 rclpy/nav_msgs dependencies are unavailable",
            )
        with self._lock:
            ready = self._snapshot is not None
        if ready and not self.dependencies.rtabmap_msgs:
            return ProviderStatus(
                "RTAB-Map SLAM",
                ProviderMode.REAL,
                True,
                "occupancy/pose active; rtabmap_msgs status is unavailable",
            )
        if not self.dependencies.rtabmap_msgs:
            return ProviderStatus(
                "RTAB-Map SLAM",
                ProviderMode.UNAVAILABLE,
                False,
                "waiting for occupancy/pose; rtabmap_msgs status unavailable",
            )
        return ProviderStatus(
            "RTAB-Map SLAM",
            ProviderMode.REAL,
            ready,
            "receiving configured ROS topics" if ready else "waiting for occupancy/pose/status topics",
        )

    def snapshot(self) -> SlamSnapshot:
        status = self.status()
        if not status.connected:
            raise DependencyUnavailableError(status.message)
        with self._lock:
            assert self._snapshot is not None
            return self._snapshot

    def reset(self) -> None:
        """Invalidate sensor state that belongs to the previous mission."""

        with self._lock:
            self._snapshot = None

    @staticmethod
    def occupancy_from_ros(message: object) -> OccupancyGrid:
        """Convert nav_msgs/OccupancyGrid by structural typing for easy tests."""

        info = message.info
        return OccupancyGrid(
            width=int(info.width),
            height=int(info.height),
            resolution=float(info.resolution),
            origin=Point2D(float(info.origin.position.x), float(info.origin.position.y)),
            data=tuple(int(value) for value in message.data),
            frame_id=str(message.header.frame_id or "map"),
        )


class AstraDepthProvider(DepthProvider):
    """Sample robust median depth at a box center using synchronized depth data."""

    def __init__(
        self,
        *,
        minimum_depth_m: float = 0.15,
        maximum_depth_m: float = 10.0,
        dependency_state: RosDependencyState | None = None,
        maximum_sync_age_s: float = 0.25,
    ) -> None:
        self.minimum_depth_m = minimum_depth_m
        self.maximum_depth_m = maximum_depth_m
        self.dependencies = dependency_state or RosDependencyState.detect()
        self.maximum_sync_age_s = maximum_sync_age_s
        self._depth: Sequence[Sequence[float | int]] | None = None
        self._depth_scale = 1.0
        self._intrinsics: CameraIntrinsics | None = None
        self._timestamp: str | None = None
        self._lock = threading.RLock()

    def update_depth(
        self,
        depth: Sequence[Sequence[float | int]],
        intrinsics: CameraIntrinsics,
        *,
        depth_scale: float = 1.0,
        timestamp: str | None = None,
    ) -> None:
        if depth_scale <= 0:
            raise ValueError("depth_scale must be positive")
        if len(depth) != intrinsics.height or any(
            len(row) != intrinsics.width for row in depth
        ):
            raise ValueError("depth image resolution does not match CameraInfo")
        with self._lock:
            self._depth = depth
            self._depth_scale = depth_scale
            self._intrinsics = intrinsics
            self._timestamp = timestamp

    def reset(self) -> None:
        """Clear the last measurement so stale depth cannot cross missions/errors."""

        with self._lock:
            self._depth = None
            self._depth_scale = 1.0
            self._intrinsics = None
            self._timestamp = None

    @staticmethod
    def _age_seconds(first: str, second: str) -> float:
        parse = lambda value: datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        )
        return abs((parse(first) - parse(second)).total_seconds())

    def status(self) -> ProviderStatus:
        if not (self.dependencies.rclpy and self.dependencies.sensor_msgs):
            return ProviderStatus(
                "Astra depth",
                ProviderMode.UNAVAILABLE,
                False,
                "ROS 2 sensor_msgs dependencies are unavailable",
            )
        with self._lock:
            ready = self._depth is not None and self._intrinsics is not None
        driver_note = "Astra driver package not detected; compatible sensor_msgs topics may still be used"
        return ProviderStatus(
            "Astra depth",
            ProviderMode.REAL,
            ready,
            "receiving depth and camera info" if ready else driver_note,
        )

    def locate(self, detection: Detection2D) -> CameraPoint | None:
        with self._lock:
            if self._depth is None or self._intrinsics is None:
                return None
            depth, scale, intrinsics = self._depth, self._depth_scale, self._intrinsics
            timestamp = self._timestamp
            if (
                timestamp is not None
                and self.maximum_sync_age_s >= 0
                and self._age_seconds(timestamp, detection.timestamp)
                > self.maximum_sync_age_s
            ):
                return None
            center_x = int(round(detection.bbox.x + detection.bbox.width / 2))
            center_y = int(round(detection.bbox.y + detection.bbox.height / 2))
            radius = max(1, int(min(detection.bbox.width, detection.bbox.height) * 0.05))
            samples = []
            for y in range(max(0, center_y - radius), min(intrinsics.height, center_y + radius + 1)):
                if y >= len(depth):
                    continue
                row = depth[y]
                for x in range(max(0, center_x - radius), min(intrinsics.width, center_x + radius + 1)):
                    if x >= len(row):
                        continue
                    measured = float(row[x]) * scale
                    if math.isfinite(measured) and self.minimum_depth_m <= measured <= self.maximum_depth_m:
                        samples.append(measured)
            if not samples:
                return None
            samples.sort()
            z = samples[len(samples) // 2]
            x = (center_x - intrinsics.cx) * z / intrinsics.fx
            y = (center_y - intrinsics.cy) * z / intrinsics.fy
            return CameraPoint(x, y, z)

    def measurement_frame_id(self) -> str | None:
        with self._lock:
            return self._intrinsics.frame_id if self._intrinsics is not None else None

    def measurement_image_size(self) -> tuple[int, int] | None:
        with self._lock:
            if self._intrinsics is None:
                return None
            return self._intrinsics.width, self._intrinsics.height


class RosMapTransformer(MapTransformer):
    """Adapter around a TF-backed callable to keep tf2 optional and testable."""

    def __init__(
        self,
        transform: Callable[[CameraPoint, str, str, str], Point2D | None] | None,
        *,
        target_frame: str = "map",
    ) -> None:
        self.transform = transform
        self.target_frame = target_frame

    def camera_to_map(
        self, point: CameraPoint, *, timestamp: str, frame_id: str
    ) -> Point2D | None:
        if self.transform is None:
            return None
        return self.transform(point, frame_id, self.target_frame, timestamp)
