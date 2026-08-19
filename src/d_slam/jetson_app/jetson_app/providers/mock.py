"""Deterministic providers for tests and explicit Mock mode."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from ..domain import (
    BoundingBox,
    CameraPoint,
    OccupancyGrid,
    PersonCandidate,
    Point2D,
    Pose2D,
)
from .base import (
    DepthProvider,
    Detection2D,
    MapTransformer,
    PersonDetectionProvider,
    ProviderMode,
    ProviderStatus,
    RgbFrame,
    SlamProvider,
    SlamSnapshot,
)


class MockSlamProvider(SlamProvider):
    def __init__(self, snapshot: SlamSnapshot | None = None) -> None:
        self._snapshot = snapshot or self.default_snapshot()

    @staticmethod
    def default_snapshot() -> SlamSnapshot:
        width = height = 12
        values = [0] * (width * height)
        for y in range(2, 10):
            if y != 6:
                values[y * width + 5] = 100
        for x in range(9, 12):
            values[x] = -1
        grid = OccupancyGrid(width, height, 0.5, Point2D(0, 0), tuple(values))
        return SlamSnapshot(
            occupancy_grid=grid,
            robot_pose=Pose2D(1.25, 1.25, 0.0),
            trajectory=(Pose2D(0.75, 0.75, 0.0), Pose2D(1.25, 1.25, 0.0)),
            explored_areas=((Point2D(0, 0), Point2D(4.5, 0), Point2D(4.5, 6), Point2D(0, 6)),),
            unknown_areas=((Point2D(4.5, 0), Point2D(6, 0), Point2D(6, 0.5), Point2D(4.5, 0.5)),),
            tracking_status="mock_tracking",
            map_version=1,
        )

    def set_snapshot(self, snapshot: SlamSnapshot) -> None:
        self._snapshot = snapshot

    def status(self) -> ProviderStatus:
        return ProviderStatus("Mock SLAM", ProviderMode.MOCK, True, "synthetic grid")

    def snapshot(self) -> SlamSnapshot:
        return self._snapshot


class MockDetectionProvider(PersonDetectionProvider):
    def __init__(self, detections: Sequence[Detection2D] = ()) -> None:
        self.detections = tuple(detections)

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            "Mock person detector", ProviderMode.MOCK, True, "synthetic detections"
        )

    def detect(self, frame: RgbFrame) -> Sequence[Detection2D]:
        return self.detections


class MockDepthProvider(DepthProvider):
    def __init__(
        self,
        locations: Mapping[str, CameraPoint | None] | None = None,
        default: CameraPoint | None = None,
    ) -> None:
        self.locations = dict(locations or {})
        self.default = default

    def status(self) -> ProviderStatus:
        return ProviderStatus("Mock depth", ProviderMode.MOCK, True, "synthetic depth")

    def locate(self, detection: Detection2D) -> CameraPoint | None:
        key = detection.tracking_id or detection.detection_id or ""
        return self.locations.get(key, self.default)

    def measurement_frame_id(self) -> str:
        return "mock_camera_frame"


def deterministic_mock_candidates() -> tuple[PersonCandidate, ...]:
    """Stable fixture used only when an API process explicitly selects Mock."""

    return (
        PersonCandidate(
            detection_id="mock-person-0001",
            tracking_id="mock-track-0001",
            class_name="person",
            bbox=BoundingBox(120, 80, 64, 144),
            confidence=0.91,
            depth_valid=True,
            camera_position=CameraPoint(0.25, 0.0, 2.25),
            map_position=Point2D(2.25, 2.25),
            detected_at="2026-01-01T00:00:00Z",
            source="explicit_mock_fixture",
        ),
    )


@dataclass(frozen=True)
class OffsetMapTransformer(MapTransformer):
    """Deterministic camera X/Z to map X/Y transform for Mock mode."""

    offset_x: float = 0.0
    offset_y: float = 0.0

    def camera_to_map(
        self, point: CameraPoint, *, timestamp: str, frame_id: str
    ) -> Point2D:
        return Point2D(point.x + self.offset_x, point.z + self.offset_y)
