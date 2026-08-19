from __future__ import annotations
from ..domain import CameraPoint, PersonCandidate, Point2D, utc_now
from ..providers.base import Detection2D

def fuse_detection(detection: Detection2D, *, camera_position: CameraPoint | None, map_position: Point2D | None, source: str = "rgbd") -> PersonCandidate:
    return PersonCandidate(detection.detection_id or f"person-{detection.timestamp}", detection.tracking_id, detection.class_name, detection.bbox, detection.confidence, camera_position is not None, camera_position, map_position, detection.timestamp or utc_now(), source)
