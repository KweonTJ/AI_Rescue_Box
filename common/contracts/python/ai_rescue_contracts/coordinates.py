"""Coordinate and provenance primitives shared by Host, UWB and d_slam."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


class CoordinateFrame(str, Enum):
    IMAGE_PX = "image_px"
    MISSION_MAP = "mission_map"
    SLAM_MAP = "slam_map"


class ObservationState(str, Enum):
    OBSERVED = "observed"
    PRIOR_ONLY = "prior_only"
    INTERPOLATED = "interpolated"
    AI_SUGGESTED = "ai_suggested"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Transform2D:
    tx: float
    ty: float
    yaw: float
    confidence: float = 1.0

    def __post_init__(self) -> None:
        for name, value in (("tx", self.tx), ("ty", self.ty), ("yaw", self.yaw)):
            if not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        if not math.isfinite(float(self.confidence)) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")

    def apply(self, x: float, y: float) -> tuple[float, float]:
        cosine, sine = math.cos(self.yaw), math.sin(self.yaw)
        return (
            cosine * x - sine * y + self.tx,
            sine * x + cosine * y + self.ty,
        )
