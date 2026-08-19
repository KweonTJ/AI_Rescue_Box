"""Fuse person boxes with measured depth; never invent missing positions."""

from __future__ import annotations

import math
import threading
import uuid
from datetime import datetime
from ..domain import PersonCandidate, Point2D, validate_timestamp
from ..providers.base import (
    DepthProvider,
    Detection2D,
    MapTransformer,
    PersonDetectionProvider,
    RgbFrame,
)


def _seconds_between(first: str, second: str) -> float:
    def parse(value: str) -> datetime:
        validate_timestamp(value)
        return datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)

    return abs((parse(first) - parse(second)).total_seconds())


def _distance(first: Point2D, second: Point2D) -> float:
    return math.hypot(first.x - second.x, first.y - second.y)


class CandidateTracker:
    """Merge repeat observations by tracking ID, or bounded time and distance."""

    def __init__(self, *, merge_distance_m: float = 0.75, merge_window_s: float = 5.0):
        if merge_distance_m <= 0 or merge_window_s <= 0:
            raise ValueError("merge distance and window must be positive")
        self.merge_distance_m = merge_distance_m
        self.merge_window_s = merge_window_s
        self._candidates: list[PersonCandidate] = []
        self._lock = threading.RLock()

    def _match(self, incoming: PersonCandidate) -> PersonCandidate | None:
        for existing in self._candidates:
            if (
                incoming.tracking_id
                and existing.tracking_id
                and incoming.tracking_id == existing.tracking_id
            ):
                return existing
            if (
                incoming.map_position is not None
                and existing.map_position is not None
                and incoming.class_name == existing.class_name
                and _seconds_between(incoming.detected_at, existing.last_seen_at or existing.detected_at)
                <= self.merge_window_s
                and _distance(incoming.map_position, existing.map_position)
                <= self.merge_distance_m
            ):
                return existing
        return None

    def add(self, candidate: PersonCandidate) -> PersonCandidate:
        with self._lock:
            existing = self._match(candidate)
            if existing is None:
                self._candidates.append(candidate)
                return candidate
            total = existing.observation_count + 1
            if existing.map_position is not None and candidate.map_position is not None:
                existing.map_position = Point2D(
                    (existing.map_position.x * existing.observation_count + candidate.map_position.x)
                    / total,
                    (existing.map_position.y * existing.observation_count + candidate.map_position.y)
                    / total,
                )
            elif candidate.map_position is not None:
                existing.map_position = candidate.map_position
            if candidate.camera_position is not None:
                existing.camera_position = candidate.camera_position
                existing.depth_valid = True
            existing.bbox = candidate.bbox
            existing.confidence = max(existing.confidence, candidate.confidence)
            existing.last_seen_at = candidate.detected_at
            existing.observation_count = total
            return existing

    def candidates(self) -> tuple[PersonCandidate, ...]:
        with self._lock:
            return tuple(self._candidates)

    def reset(self) -> None:
        """Discard observations at an explicit mission boundary."""

        with self._lock:
            self._candidates.clear()


class PersonFusionEngine:
    def __init__(
        self,
        detector: PersonDetectionProvider,
        depth: DepthProvider,
        transformer: MapTransformer,
        tracker: CandidateTracker | None = None,
    ) -> None:
        self.detector = detector
        self.depth = depth
        self.transformer = transformer
        self.tracker = tracker or CandidateTracker()

    @staticmethod
    def _id_for(detection: Detection2D) -> str:
        if detection.detection_id:
            return detection.detection_id
        seed = (
            f"{detection.timestamp}:{detection.tracking_id}:"
            f"{detection.bbox.x:.3f}:{detection.bbox.y:.3f}:"
            f"{detection.bbox.width:.3f}:{detection.bbox.height:.3f}"
        )
        return f"person-{uuid.uuid5(uuid.NAMESPACE_URL, seed).hex[:12]}"

    def process(self, frame: RgbFrame) -> tuple[PersonCandidate, ...]:
        for detection in self.detector.detect(frame):
            if detection.class_name != "person":
                continue
            depth_size = self.depth.measurement_image_size()
            # A detector bbox may index Depth directly only when the driver
            # publishes RGB-aligned/registered Depth at the same pixel size.
            camera_point = (
                self.depth.locate(detection)
                if depth_size is None or depth_size == (frame.width, frame.height)
                else None
            )
            map_point = None
            if camera_point is not None:
                # Depth deprojection produces a point in the CameraInfo frame,
                # not necessarily the RGB optical frame. Refuse an ambiguous
                # frame instead of applying TF from the wrong sensor frame.
                depth_frame = self.depth.measurement_frame_id()
                if depth_frame:
                    map_point = self.transformer.camera_to_map(
                        camera_point,
                        timestamp=detection.timestamp,
                        frame_id=depth_frame,
                    )
            candidate = PersonCandidate(
                detection_id=self._id_for(detection),
                tracking_id=detection.tracking_id,
                class_name=detection.class_name,
                bbox=detection.bbox,
                confidence=detection.confidence,
                depth_valid=camera_point is not None,
                camera_position=camera_point,
                map_position=map_point,
                detected_at=detection.timestamp,
                source="rgb_person_detector+measured_depth",
            )
            self.tracker.add(candidate)
        return self.tracker.candidates()

    def reset(self) -> None:
        self.tracker.reset()
