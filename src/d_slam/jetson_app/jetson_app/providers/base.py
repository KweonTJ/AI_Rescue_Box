"""Narrow interfaces separating analysis code from ROS and hardware."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Sequence

from ..domain import (
    BoundingBox,
    CameraPoint,
    OccupancyGrid,
    PersonCandidate,
    Point2D,
    Pose2D,
    RiskZone,
    RoutePlan,
    TeamRecommendation,
    utc_now,
)


class DependencyUnavailableError(RuntimeError):
    """An optional hardware/runtime dependency is not installed or ready."""


class ProviderMode(str, Enum):
    REAL = "real"
    MOCK = "mock"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ProviderStatus:
    name: str
    mode: ProviderMode
    connected: bool
    message: str
    updated_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class CameraIntrinsics:
    width: int
    height: int
    fx: float
    fy: float
    cx: float
    cy: float
    frame_id: str = "camera_depth_optical_frame"

    def __post_init__(self) -> None:
        if self.width < 1 or self.height < 1:
            raise ValueError("camera dimensions must be positive")
        if not all(math.isfinite(float(value)) for value in (self.fx, self.fy, self.cx, self.cy)):
            raise ValueError("camera intrinsics must be finite")
        if self.fx <= 0 or self.fy <= 0:
            raise ValueError("camera focal lengths must be positive")
        if not self.frame_id:
            raise ValueError("camera frame_id is required")


@dataclass(frozen=True)
class RgbFrame:
    width: int
    height: int
    data: Any
    encoding: str = "rgb8"
    frame_id: str = "camera_color_optical_frame"
    timestamp: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class Detection2D:
    bbox: BoundingBox
    confidence: float
    class_name: str = "person"
    tracking_id: str | None = None
    detection_id: str | None = None
    timestamp: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class SlamSnapshot:
    occupancy_grid: OccupancyGrid
    robot_pose: Pose2D
    trajectory: tuple[Pose2D, ...]
    explored_areas: tuple[tuple[Point2D, ...], ...]
    unknown_areas: tuple[tuple[Point2D, ...], ...]
    tracking_status: str
    map_version: int
    timestamp: str = field(default_factory=utc_now)
    sensor_risks: tuple[RiskZone, ...] = ()


class SlamProvider(ABC):
    @abstractmethod
    def status(self) -> ProviderStatus:
        raise NotImplementedError

    @abstractmethod
    def snapshot(self) -> SlamSnapshot:
        raise NotImplementedError


class PersonDetectionProvider(ABC):
    @abstractmethod
    def status(self) -> ProviderStatus:
        raise NotImplementedError

    @abstractmethod
    def detect(self, frame: RgbFrame) -> Sequence[Detection2D]:
        raise NotImplementedError


class DepthProvider(ABC):
    @abstractmethod
    def status(self) -> ProviderStatus:
        raise NotImplementedError

    @abstractmethod
    def locate(self, detection: Detection2D) -> CameraPoint | None:
        """Return a measured camera-frame point, or None for invalid depth."""

    def measurement_frame_id(self) -> str | None:
        return None

    def measurement_image_size(self) -> tuple[int, int] | None:
        return None


class MapTransformer(ABC):
    @abstractmethod
    def camera_to_map(
        self, point: CameraPoint, *, timestamp: str, frame_id: str
    ) -> Point2D | None:
        raise NotImplementedError


class RiskAssessmentProvider(ABC):
    @abstractmethod
    def assess(self, snapshot: SlamSnapshot) -> Sequence[RiskZone]:
        raise NotImplementedError


class RoutePlanningProvider(ABC):
    @abstractmethod
    def plan(
        self,
        grid: OccupancyGrid,
        start: Point2D,
        goal: Point2D,
        risks: Sequence[RiskZone],
        *,
        map_version: int,
        target_id: str | None = None,
    ) -> RoutePlan:
        raise NotImplementedError


class TeamRecommendationProvider(ABC):
    @abstractmethod
    def recommend(
        self,
        *,
        team_count: int,
        rescuer_count: int,
        candidates: Sequence[PersonCandidate],
        routes: Sequence[RoutePlan],
        waiting_points: Sequence[Point2D],
        priorities: dict[str, int] | None = None,
    ) -> Sequence[TeamRecommendation]:
        raise NotImplementedError
