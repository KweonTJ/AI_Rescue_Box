"""Conservative prior-map versus observed-SLAM extent sanity checks."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .domain import MissionManifest
from .providers import SlamSnapshot


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


__all__ = ["PriorSlamAlignmentEvaluator"]
