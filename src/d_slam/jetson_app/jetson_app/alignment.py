"""Conservative Stage 3 mission-frame anchoring and prior-map sanity checks.

The rigid transform in this module is deliberately *not* automatic map
alignment.  Stage 3 only anchors the live RTAB-Map frame to the mission frame
from either an explicit operator configuration or the mission-start pose.
Feature/ICP alignment remains a Stage 4 responsibility.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from typing import Any

from .domain import MissionManifest, Point2D, Pose2D
from .providers import SlamSnapshot


def _normalize_yaw(value: float) -> float:
    return math.atan2(math.sin(value), math.cos(value))


@dataclass(frozen=True)
class RigidMissionTransform:
    """2-D ``T_mission_map_from_slam_map`` used only as a provisional anchor."""

    translation_x_m: float
    translation_y_m: float
    yaw_radians: float
    mode: str
    status: str

    def slam_to_mission_point(self, point: Point2D) -> Point2D:
        cosine, sine = math.cos(self.yaw_radians), math.sin(self.yaw_radians)
        return Point2D(
            cosine * point.x - sine * point.y + self.translation_x_m,
            sine * point.x + cosine * point.y + self.translation_y_m,
        )

    def mission_to_slam_point(self, point: Point2D) -> Point2D:
        x = point.x - self.translation_x_m
        y = point.y - self.translation_y_m
        cosine, sine = math.cos(self.yaw_radians), math.sin(self.yaw_radians)
        return Point2D(cosine * x + sine * y, -sine * x + cosine * y)

    def slam_to_mission_pose(self, pose: Pose2D) -> Pose2D:
        point = self.slam_to_mission_point(Point2D(pose.x, pose.y))
        return Pose2D(point.x, point.y, _normalize_yaw(pose.yaw + self.yaw_radians))

    def metadata(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "status": self.status,
            "automatic_map_alignment": False,
            "stage4_alignment_required": True,
            "T_mission_map_from_slam_map": {
                "translation_x_m": self.translation_x_m,
                "translation_y_m": self.translation_y_m,
                "yaw_radians": self.yaw_radians,
            },
        }


class ProvisionalMissionTransform:
    """Resolve and cache the Stage 3 live-SLAM to mission-map transform."""

    def __init__(
        self,
        *,
        mode: str = "initial_anchor",
        translation_x_m: float | None = None,
        translation_y_m: float | None = None,
        yaw_radians: float | None = None,
    ) -> None:
        if mode not in {"initial_anchor", "configured"}:
            raise ValueError("mission transform mode must be initial_anchor or configured")
        if mode == "configured" and any(
            value is None
            for value in (translation_x_m, translation_y_m, yaw_radians)
        ):
            raise ValueError("configured mission transform requires x, y and yaw")
        self.mode = mode
        self.translation_x_m = translation_x_m
        self.translation_y_m = translation_y_m
        self.yaw_radians = yaw_radians
        self._lock = threading.RLock()
        self._mission_key: tuple[str, int] | None = None
        self._resolved: RigidMissionTransform | None = None

    @staticmethod
    def identity_for_mock() -> RigidMissionTransform:
        return RigidMissionTransform(0.0, 0.0, 0.0, "mock_identity", "available")

    def reset(self) -> None:
        with self._lock:
            self._mission_key = None
            self._resolved = None

    def resolve(
        self, mission: MissionManifest, slam_start_pose: Pose2D
    ) -> RigidMissionTransform:
        if self.mode == "configured":
            assert self.translation_x_m is not None
            assert self.translation_y_m is not None
            assert self.yaw_radians is not None
            return RigidMissionTransform(
                float(self.translation_x_m),
                float(self.translation_y_m),
                _normalize_yaw(float(self.yaw_radians)),
                "configured",
                "available",
            )

        key = (mission.mission_id, mission.mission_version)
        with self._lock:
            if self._mission_key == key and self._resolved is not None:
                return self._resolved
            yaw = _normalize_yaw(mission.robot_start.yaw - slam_start_pose.yaw)
            cosine, sine = math.cos(yaw), math.sin(yaw)
            rotated_x = cosine * slam_start_pose.x - sine * slam_start_pose.y
            rotated_y = sine * slam_start_pose.x + cosine * slam_start_pose.y
            resolved = RigidMissionTransform(
                mission.robot_start.x - rotated_x,
                mission.robot_start.y - rotated_y,
                yaw,
                "initial_anchor",
                "provisional",
            )
            self._mission_key = key
            self._resolved = resolved
            return resolved


@dataclass(frozen=True)
class PriorSlamAlignmentEvaluator:
    """Classify evidence without claiming feature alignment or warping maps."""

    min_known_cells: int = 25
    min_span_cells: int = 3
    relative_mismatch_margin: float = 0.5
    absolute_mismatch_margin_m: float = 2.0

    def evaluate(
        self, mission: MissionManifest, snapshot: SlamSnapshot
    ) -> dict[str, Any]:
        grid = snapshot.occupancy_grid
        known = [
            (x, y)
            for y in range(grid.height)
            for x in range(grid.width)
            if grid.value(x, y) != -1
        ]
        transform = mission.coordinate_transform
        rotation = float(transform.get("rotation_radians", 0.0))
        image_width_m = mission.base_map_width * mission.meters_per_pixel
        image_height_m = mission.base_map_height * mission.meters_per_pixel
        cosine = abs(math.cos(rotation))
        sine = abs(math.sin(rotation))
        prior_width = cosine * image_width_m + sine * image_height_m
        prior_height = sine * image_width_m + cosine * image_height_m

        common: dict[str, Any] = {
            "source": "prior_bounds_vs_slam_observed_extent",
            "method": "extent_sanity_check_only",
            "automatic_warp_applied": False,
            "alignment_confirmed": False,
            "prior_extent_m": {
                "width": round(prior_width, 6),
                "height": round(prior_height, 6),
            },
            "observed_known_cells": len(known),
            "slam_map_version": snapshot.map_version,
        }
        if not known:
            return {
                **common,
                "status": "insufficient_evidence",
                "confidence": 0.0,
                "observed_extent_m": {"width": 0.0, "height": 0.0},
                "warning": "관측된 SLAM cell이 없어 prior 지도 정합을 평가하지 않았습니다.",
            }

        xs = [cell[0] for cell in known]
        ys = [cell[1] for cell in known]
        span_x_cells = max(xs) - min(xs) + 1
        span_y_cells = max(ys) - min(ys) + 1
        observed_width = span_x_cells * grid.resolution
        observed_height = span_y_cells * grid.resolution
        common["observed_extent_m"] = {
            "width": round(observed_width, 6),
            "height": round(observed_height, 6),
        }

        if (
            len(known) < self.min_known_cells
            or span_x_cells < self.min_span_cells
            or span_y_cells < self.min_span_cells
        ):
            return {
                **common,
                "status": "insufficient_evidence",
                "confidence": 0.0,
                "warning": "관측 범위가 작아 prior 지도 정합 성공을 판단하지 않았습니다.",
            }

        width_limit = prior_width + max(
            self.absolute_mismatch_margin_m,
            prior_width * self.relative_mismatch_margin,
        )
        height_limit = prior_height + max(
            self.absolute_mismatch_margin_m,
            prior_height * self.relative_mismatch_margin,
        )
        if observed_width > width_limit or observed_height > height_limit:
            return {
                **common,
                "status": "mismatch_candidate",
                "confidence": 0.25,
                "warning": (
                    "관측 SLAM 범위가 prior 물리 경계를 큰 margin으로 초과합니다. "
                    "좌표계·축척·초기 자세를 현장에서 확인하세요."
                ),
            }

        return {
            **common,
            "status": "initial_pose_overlay",
            "confidence": 0.2,
            "warning": (
                "초기 자세 기준 overlay만 사용합니다. feature 정합 성공을 뜻하지 않으며 "
                "자동 image warp를 수행하지 않았습니다."
            ),
        }


__all__ = [
    "PriorSlamAlignmentEvaluator",
    "ProvisionalMissionTransform",
    "RigidMissionTransform",
]
