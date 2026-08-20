from __future__ import annotations

import math
from dataclasses import replace
from typing import Sequence

from ..alignment import RigidMissionTransform
from ..domain import MissionManifest, OccupancyGrid, Point2D
from ..providers import SlamSnapshot
from .models import (
    AlignmentResult,
    ChangeMap,
    PRIOR_FREE,
    PRIOR_OCCUPIED,
    PRIOR_UNKNOWN,
    PriorMapReference,
    Stage4Config,
)


class PriorLiveMapAligner:
    """Bounded coarse-to-fine SE(2) search around the Stage 3 initial anchor."""

    def __init__(self, config: Stage4Config, *, occupied_threshold: int = 65) -> None:
        self.config = config
        self.occupied_threshold = occupied_threshold

    @staticmethod
    def _frange(center: float, radius: float, step: float) -> tuple[float, ...]:
        count = int(math.floor(radius / step + 1e-9))
        return tuple(center + index * step for index in range(-count, count + 1))

    def _evidence(self, grid: OccupancyGrid) -> tuple[tuple[tuple[Point2D, int], ...], int, int]:
        known: list[tuple[Point2D, int]] = []
        occupied = 0
        for y in range(grid.height):
            for x in range(grid.width):
                value = grid.value(x, y)
                if value == -1:
                    continue
                known.append((grid.cell_to_world((x, y)), value))
                occupied += int(value >= self.occupied_threshold)
        if len(known) > self.config.alignment_max_samples:
            stride = math.ceil(len(known) / self.config.alignment_max_samples)
            sampled = tuple(known[::stride])
        else:
            sampled = tuple(known)
        return sampled, len(known), occupied

    def _score(
        self,
        prior: PriorMapReference,
        evidence: Sequence[tuple[Point2D, int]],
        transform: RigidMissionTransform,
    ) -> tuple[float, float, float, float]:
        covered = occupied_total = occupied_match = free_total = free_conflicts = 0
        for point, live_value in evidence:
            prior_value = prior.sample_mission(transform.slam_to_mission_point(point))
            if prior_value == PRIOR_UNKNOWN:
                continue
            covered += 1
            if live_value >= self.occupied_threshold:
                occupied_total += 1
                occupied_match += int(prior_value == PRIOR_OCCUPIED)
            else:
                free_total += 1
                free_conflicts += int(prior_value == PRIOR_OCCUPIED)
        coverage = covered / max(1, len(evidence))
        overlap = occupied_match / max(1, occupied_total)
        conflict = free_conflicts / max(1, free_total)
        score = 0.60 * overlap + 0.30 * coverage + 0.10 * (1 - conflict) - 0.35 * conflict
        return score, overlap, coverage, conflict

    @staticmethod
    def _distance(candidate: RigidMissionTransform, initial: RigidMissionTransform) -> float:
        yaw = math.atan2(
            math.sin(candidate.yaw_radians - initial.yaw_radians),
            math.cos(candidate.yaw_radians - initial.yaw_radians),
        )
        return math.hypot(
            candidate.translation_x_m - initial.translation_x_m,
            candidate.translation_y_m - initial.translation_y_m,
        ) + abs(yaw)

    def _search(
        self,
        prior: PriorMapReference,
        evidence: Sequence[tuple[Point2D, int]],
        initial: RigidMissionTransform,
        center: RigidMissionTransform,
        *,
        xy_radius: float,
        xy_step: float,
        yaw_radius: float,
        yaw_step: float,
    ) -> tuple[RigidMissionTransform, tuple[float, float, float, float]]:
        best = center
        best_metrics = self._score(prior, evidence, best)
        for yaw in self._frange(center.yaw_radians, yaw_radius, yaw_step):
            for ty in self._frange(center.translation_y_m, xy_radius, xy_step):
                for tx in self._frange(center.translation_x_m, xy_radius, xy_step):
                    candidate = RigidMissionTransform(tx, ty, yaw, "prior_live_alignment", "candidate")
                    metrics = self._score(prior, evidence, candidate)
                    if (metrics[0], -self._distance(candidate, initial)) > (
                        best_metrics[0], -self._distance(best, initial)
                    ):
                        best, best_metrics = candidate, metrics
        return best, best_metrics

    def align(
        self,
        mission: MissionManifest,
        prior: PriorMapReference,
        snapshot: SlamSnapshot,
        initial: RigidMissionTransform,
    ) -> AlignmentResult:
        evidence, total_known, total_occupied = self._evidence(snapshot.occupancy_grid)
        prior_occupied = sum(value == PRIOR_OCCUPIED for value in prior.states)
        if (
            total_known < self.config.alignment_min_known_cells
            or total_occupied < self.config.alignment_min_occupied_cells
            or prior_occupied < self.config.alignment_min_occupied_cells
        ):
            return AlignmentResult(
                initial, "insufficient_evidence", 0.0, 0.0, 0.0, 0.0, 0.0,
                "bounded_se2_prior_live", True, False, mission.mission_version,
                snapshot.map_version, total_known, total_occupied,
            )
        coarse, _ = self._search(
            prior, evidence, initial, initial,
            xy_radius=self.config.alignment_translation_search_m,
            xy_step=self.config.alignment_translation_coarse_step_m,
            yaw_radius=self.config.alignment_yaw_search_radians,
            yaw_step=self.config.alignment_yaw_coarse_step_radians,
        )
        best, metrics = self._search(
            prior, evidence, initial, coarse,
            xy_radius=self.config.alignment_translation_coarse_step_m,
            xy_step=self.config.alignment_translation_fine_step_m,
            yaw_radius=self.config.alignment_yaw_coarse_step_radians,
            yaw_step=self.config.alignment_yaw_fine_step_radians,
        )
        score, overlap, coverage, conflict = metrics
        confidence = max(0.0, min(1.0, 0.60 * overlap + 0.30 * coverage + 0.10 * (1 - conflict)))
        aligned = (
            confidence >= self.config.alignment_min_confidence
            and overlap >= self.config.alignment_min_overlap
            and coverage >= self.config.alignment_min_coverage
        )
        selected = replace(best, status="aligned") if aligned else initial
        return AlignmentResult(
            selected,
            "aligned" if aligned else "low_confidence",
            confidence,
            overlap,
            coverage,
            conflict,
            score,
            "bounded_se2_prior_live",
            not aligned,
            aligned,
            mission.mission_version,
            snapshot.map_version,
            total_known,
            total_occupied,
        )


class ChangeMapBuilder:
    def __init__(self, *, occupied_threshold: int = 65) -> None:
        self.occupied_threshold = occupied_threshold

    def build(
        self,
        prior: PriorMapReference,
        snapshot: SlamSnapshot,
        alignment: AlignmentResult,
    ) -> ChangeMap:
        grid = snapshot.occupancy_grid
        classes: list[str] = []
        changed = []
        for y in range(grid.height):
            for x in range(grid.width):
                live = grid.value(x, y)
                slam_point = grid.cell_to_world((x, y))
                mission_point = alignment.transform.slam_to_mission_point(slam_point)
                if live == -1:
                    kind = "not_observed"
                elif not alignment.automatic_map_alignment:
                    kind = "no_prior_reference"
                else:
                    prior_value = prior.sample_mission(mission_point)
                    if prior_value == PRIOR_UNKNOWN:
                        kind = "no_prior_reference"
                    elif prior_value == PRIOR_FREE and live >= self.occupied_threshold:
                        kind = "newly_blocked"
                    elif prior_value == PRIOR_OCCUPIED and live < self.occupied_threshold:
                        kind = "cleared_or_opened"
                    else:
                        kind = "unchanged"
                classes.append(kind)
                if kind in {"newly_blocked", "cleared_or_opened"}:
                    changed.append({
                        "state": kind,
                        "mission_position": mission_point.to_dict(),
                        "slam_cell": {"x": x, "y": y},
                    })
        return ChangeMap(
            grid.width,
            grid.height,
            tuple(classes),
            alignment.automatic_map_alignment,
            snapshot.map_version,
            tuple(changed),
        )
