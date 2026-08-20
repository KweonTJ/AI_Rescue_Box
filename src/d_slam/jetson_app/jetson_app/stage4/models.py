from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from PIL import Image

from ..alignment import RigidMissionTransform
from ..domain import MissionManifest, OccupancyGrid, Point2D

PRIOR_UNKNOWN = -1
PRIOR_FREE = 0
PRIOR_OCCUPIED = 100


@dataclass(frozen=True)
class Stage4Config:
    prior_dark_threshold: int = 64
    prior_free_threshold: int = 220
    alignment_translation_search_m: float = 1.5
    alignment_translation_coarse_step_m: float = 0.25
    alignment_translation_fine_step_m: float = 0.05
    alignment_yaw_search_radians: float = math.radians(10.0)
    alignment_yaw_coarse_step_radians: float = math.radians(5.0)
    alignment_yaw_fine_step_radians: float = math.radians(1.0)
    alignment_min_confidence: float = 0.55
    alignment_min_overlap: float = 0.35
    alignment_min_coverage: float = 0.20
    alignment_min_known_cells: int = 25
    alignment_min_occupied_cells: int = 8
    alignment_max_samples: int = 2500
    robot_clearance_m: float = 0.25
    prior_reference_wall_block: bool = True
    narrow_passage_cost_value: int = 45
    traversability_risk_weight: float = 30.0
    traversability_block_risk_severity: float = 0.85
    route_candidate_count: int = 3
    route_distinctness_min: float = 0.20
    route_corridor_radius_cells: int = 0
    route_score_distance_weight: float = 1.0
    route_score_risk_weight: float = 1.0
    route_score_unknown_weight: float = 10.0
    route_score_change_weight: float = 5.0
    route_score_clearance_weight: float = 1.0
    safe_zone_count: int = 3
    safe_zone_min_clearance_m: float = 0.50
    safe_zone_spacing_m: float = 1.0
    safe_zone_change_distance_m: float = 0.75
    safe_zone_risk_block_severity: float = 0.70

    def __post_init__(self) -> None:
        if not 0 <= self.prior_dark_threshold < self.prior_free_threshold <= 255:
            raise ValueError("prior thresholds must satisfy 0 <= dark < free <= 255")
        positive = (
            self.alignment_translation_search_m,
            self.alignment_translation_coarse_step_m,
            self.alignment_translation_fine_step_m,
            self.alignment_yaw_search_radians,
            self.alignment_yaw_coarse_step_radians,
            self.alignment_yaw_fine_step_radians,
            self.robot_clearance_m,
            self.safe_zone_min_clearance_m,
            self.safe_zone_spacing_m,
            self.safe_zone_change_distance_m,
        )
        if any(value <= 0 for value in positive):
            raise ValueError("Stage 4 distances/search steps must be positive")
        normalized = (
            self.alignment_min_confidence,
            self.alignment_min_overlap,
            self.alignment_min_coverage,
            self.route_distinctness_min,
            self.safe_zone_risk_block_severity,
            self.traversability_block_risk_severity,
        )
        if any(not 0 <= value <= 1 for value in normalized):
            raise ValueError("Stage 4 normalized thresholds must be in [0, 1]")
        if self.alignment_min_known_cells < 1 or self.alignment_min_occupied_cells < 1:
            raise ValueError("Stage 4 alignment evidence counts must be positive")
        if self.alignment_max_samples < self.alignment_min_known_cells:
            raise ValueError("alignment_max_samples is too small")
        if not 0 <= self.narrow_passage_cost_value < 100:
            raise ValueError("narrow_passage_cost_value must be in [0, 99]")
        if self.route_candidate_count < 1 or self.safe_zone_count < 0:
            raise ValueError("Stage 4 candidate counts are invalid")
        if self.route_corridor_radius_cells < 0 or self.traversability_risk_weight < 0:
            raise ValueError("Stage 4 cost/radius values cannot be negative")


@dataclass(frozen=True)
class PriorMapReference:
    width: int
    height: int
    meters_per_pixel: float
    image_origin_x: float
    image_origin_y: float
    rotation_radians: float
    invert_y: bool
    states: tuple[int, ...]
    source: str

    @classmethod
    def from_image(
        cls,
        mission: MissionManifest,
        image_path: Path,
        *,
        dark_threshold: int,
        free_threshold: int,
    ) -> "PriorMapReference":
        with Image.open(image_path) as image:
            gray = image.convert("L")
            if gray.size != (mission.base_map_width, mission.base_map_height):
                raise ValueError("prior image dimensions do not match mission manifest")
            pixels = tuple(int(value) for value in gray.getdata())
        transform = mission.coordinate_transform
        origin = transform.get("image_origin", {}) if isinstance(transform, Mapping) else {}
        if isinstance(origin, Mapping):
            ox = float(origin.get("x", 0.0))
            oy = float(origin.get("y", mission.base_map_height - 1.0))
        else:
            ox, oy = 0.0, mission.base_map_height - 1.0
        rotation = float(transform.get("rotation_radians", 0.0)) if isinstance(transform, Mapping) else 0.0
        invert_y = bool(transform.get("invert_y", True)) if isinstance(transform, Mapping) else True
        states = tuple(
            PRIOR_OCCUPIED if value <= dark_threshold else PRIOR_FREE if value >= free_threshold else PRIOR_UNKNOWN
            for value in pixels
        )
        return cls(
            mission.base_map_width,
            mission.base_map_height,
            mission.meters_per_pixel,
            ox,
            oy,
            rotation,
            invert_y,
            states,
            str(image_path),
        )

    def value(self, x: int, y: int) -> int:
        if not (0 <= x < self.width and 0 <= y < self.height):
            return PRIOR_UNKNOWN
        return self.states[y * self.width + x]

    def image_to_mission(self, x: float, y: float) -> Point2D:
        dx = (x - self.image_origin_x) * self.meters_per_pixel
        dy = (y - self.image_origin_y) * self.meters_per_pixel
        if self.invert_y:
            dy = -dy
        cosine, sine = math.cos(self.rotation_radians), math.sin(self.rotation_radians)
        return Point2D(cosine * dx - sine * dy, sine * dx + cosine * dy)

    def mission_to_image(self, point: Point2D) -> tuple[float, float]:
        cosine, sine = math.cos(self.rotation_radians), math.sin(self.rotation_radians)
        dx = cosine * point.x + sine * point.y
        dy = -sine * point.x + cosine * point.y
        if self.invert_y:
            dy = -dy
        return (
            self.image_origin_x + dx / self.meters_per_pixel,
            self.image_origin_y + dy / self.meters_per_pixel,
        )

    def sample_mission(self, point: Point2D) -> int:
        x, y = self.mission_to_image(point)
        return self.value(int(math.floor(x)), int(math.floor(y)))

    def metadata(self) -> dict[str, Any]:
        counts = Counter(self.states)
        return {
            "source": "host_prior_map",
            "preprocessing": "grayscale_threshold_reference",
            "width": self.width,
            "height": self.height,
            "meters_per_pixel": self.meters_per_pixel,
            "occupied_pixels": counts[PRIOR_OCCUPIED],
            "free_pixels": counts[PRIOR_FREE],
            "unknown_pixels": counts[PRIOR_UNKNOWN],
            "coordinate_transform": {
                "image_origin": {"x": self.image_origin_x, "y": self.image_origin_y},
                "rotation_radians": self.rotation_radians,
                "invert_y": self.invert_y,
                "frame_id": "mission_map",
            },
        }


@dataclass(frozen=True)
class AlignmentResult:
    transform: RigidMissionTransform
    status: str
    confidence: float
    overlap: float
    coverage: float
    free_conflict: float
    score: float
    source: str
    fallback: bool
    automatic_map_alignment: bool
    prior_map_version: int
    live_map_version: int
    evidence_cells: int
    occupied_evidence_cells: int

    def metadata(self) -> dict[str, Any]:
        transform = {
            "translation_x_m": self.transform.translation_x_m,
            "translation_y_m": self.transform.translation_y_m,
            "yaw_radians": self.transform.yaw_radians,
        }
        return {
            "mode": "prior_live_alignment",
            "status": self.status,
            "fallback_transform_mode": self.transform.mode if self.fallback else None,
            "transform": transform,
            "T_mission_map_from_slam_map": transform,
            "confidence": round(self.confidence, 6),
            "overlap": round(self.overlap, 6),
            "coverage": round(self.coverage, 6),
            "free_conflict": round(self.free_conflict, 6),
            "score": round(self.score, 6),
            "source": self.source,
            "fallback": self.fallback,
            "automatic_map_alignment": self.automatic_map_alignment,
            "stage4_alignment_required": not self.automatic_map_alignment,
            "prior_map_version": self.prior_map_version,
            "live_map_version": self.live_map_version,
            "evidence_cells": self.evidence_cells,
            "occupied_evidence_cells": self.occupied_evidence_cells,
        }


@dataclass(frozen=True)
class ChangeMap:
    width: int
    height: int
    classes: tuple[str, ...]
    aligned: bool
    map_version: int
    changed_points: tuple[Mapping[str, Any], ...] = ()

    def value(self, x: int, y: int) -> str:
        return self.classes[y * self.width + x]

    def cells(self, kind: str) -> tuple[tuple[int, int], ...]:
        return tuple(
            (index % self.width, index // self.width)
            for index, value in enumerate(self.classes)
            if value == kind
        )

    def metadata(self, *, include_cells: bool = True) -> dict[str, Any]:
        value = {
            "classification": "rule_based_prior_vs_observed_live",
            "comparison_enabled": self.aligned,
            "map_version": self.map_version,
            "counts": dict(sorted(Counter(self.classes).items())),
            "changed_cell_count": len(self.changed_points),
            "live_unknown_policy": "not_observed",
        }
        if include_cells:
            value["changed_cells"] = list(self.changed_points)
        return value


@dataclass(frozen=True)
class TraversabilityMap:
    grid: OccupancyGrid
    clearance_m: tuple[float, ...]
    states: tuple[str, ...]
    observed_free_cells: frozenset[tuple[int, int]]
    blocked_cells: frozenset[tuple[int, int]]
    prior_reference_cells: frozenset[tuple[int, int]]

    def clearance(self, cell: tuple[int, int]) -> float:
        return self.clearance_m[cell[1] * self.grid.width + cell[0]]

    def metadata(self) -> dict[str, Any]:
        finite = [value for value in self.clearance_m if math.isfinite(value)]
        return {
            "frame_id": self.grid.frame_id,
            "source": "live_observation_first",
            "counts": dict(sorted(Counter(self.states).items())),
            "robot_clearance_applied": True,
            "prior_reference_only_cells": len(self.prior_reference_cells),
            "minimum_clearance_m": min(finite, default=None),
            "maximum_clearance_m": max(finite, default=None),
        }


@dataclass(frozen=True)
class Stage4Artifacts:
    prior: PriorMapReference
    alignment: AlignmentResult
    change: ChangeMap
    traversability: TraversabilityMap
    route_evaluations: tuple[Mapping[str, Any], ...] = ()
    safe_zone_evaluations: tuple[Mapping[str, Any], ...] = ()

    def metadata(self, *, include_change_cells: bool = True) -> dict[str, Any]:
        return {
            "prior_map": self.prior.metadata(),
            "alignment": self.alignment.metadata(),
            "change_map": self.change.metadata(include_cells=include_change_cells),
            "traversability": self.traversability.metadata(),
            "route_evaluations": [dict(item) for item in self.route_evaluations],
            "safe_zone_evaluations": [dict(item) for item in self.safe_zone_evaluations],
            "map_completion": {
                "observed_live_precedence": True,
                "unobserved_prior_policy": "reference_only",
                "prior_reference_confidence": "low",
            },
        }
