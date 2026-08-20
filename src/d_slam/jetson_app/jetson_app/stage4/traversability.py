from __future__ import annotations

import math
from collections import deque
from typing import Sequence

from ..domain import OccupancyGrid, RiskZone
from ..planning.astar import point_in_polygon
from ..providers import SlamSnapshot
from .models import (
    AlignmentResult,
    ChangeMap,
    PRIOR_OCCUPIED,
    PRIOR_UNKNOWN,
    PriorMapReference,
    Stage4Config,
    TraversabilityMap,
)


class TraversabilityBuilder:
    def __init__(
        self,
        config: Stage4Config,
        *,
        occupied_threshold: int = 65,
        minimum_passage_width_m: float = 0.8,
    ) -> None:
        self.config = config
        self.occupied_threshold = occupied_threshold
        self.minimum_passage_width_m = minimum_passage_width_m

    @staticmethod
    def _distance_cells(width: int, height: int, blocked: set[tuple[int, int]]) -> list[int]:
        far = width + height + 1
        distance = [far] * (width * height)
        queue: deque[tuple[int, int]] = deque()
        for x, y in blocked:
            distance[y * width + x] = 0
            queue.append((x, y))
        while queue:
            x, y = queue.popleft()
            base = distance[y * width + x]
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if not (0 <= nx < width and 0 <= ny < height):
                    continue
                index = ny * width + nx
                if distance[index] > base + 1:
                    distance[index] = base + 1
                    queue.append((nx, ny))
        return distance

    def build(
        self,
        prior: PriorMapReference,
        snapshot: SlamSnapshot,
        alignment: AlignmentResult,
        change: ChangeMap,
        risks: Sequence[RiskZone] = (),
    ) -> TraversabilityMap:
        live = snapshot.occupancy_grid
        live_blocked = {
            (x, y)
            for y in range(live.height)
            for x in range(live.width)
            if live.value(x, y) >= self.occupied_threshold
        }
        distances = self._distance_cells(live.width, live.height, live_blocked)
        inflation_m = self.config.robot_clearance_m
        narrow_m = max(inflation_m, self.minimum_passage_width_m / 2.0)
        clearance = tuple(value * live.resolution for value in distances)
        data: list[int] = []
        states: list[str] = []
        observed_free: set[tuple[int, int]] = set()
        blocked: set[tuple[int, int]] = set()
        prior_reference: set[tuple[int, int]] = set()

        cost_risks = tuple(
            risk for risk in risks
            if risk.risk_type not in {"obstacle_candidate", "unknown_area"}
        )
        for y in range(live.height):
            for x in range(live.width):
                cell = (x, y)
                value = live.value(x, y)
                distance_m = clearance[y * live.width + x]
                if value >= self.occupied_threshold or distance_m <= inflation_m:
                    adapted, state = 100, "blocked"
                    blocked.add(cell)
                elif value == -1:
                    mission_point = alignment.transform.slam_to_mission_point(live.cell_to_world(cell))
                    prior_value = prior.sample_mission(mission_point)
                    if (
                        alignment.automatic_map_alignment
                        and prior_value == PRIOR_OCCUPIED
                        and self.config.prior_reference_wall_block
                    ):
                        adapted, state = 100, "prior_reference_blocked"
                        blocked.add(cell)
                        prior_reference.add(cell)
                    else:
                        adapted, state = -1, "unknown"
                        if prior_value != PRIOR_UNKNOWN:
                            prior_reference.add(cell)
                            state = "prior_reference_unknown"
                else:
                    observed_free.add(cell)
                    point = live.cell_to_world(cell)
                    risk = max(
                        (item.severity for item in cost_risks if point_in_polygon(point, item.polygon)),
                        default=0.0,
                    )
                    adapted = max(0, min(value, self.occupied_threshold - 1))
                    if risk >= self.config.traversability_block_risk_severity:
                        adapted, state = 100, "blocked_risk"
                        blocked.add(cell)
                        observed_free.discard(cell)
                    elif distance_m <= narrow_m or risk > 0:
                        adapted = max(
                            adapted,
                            self.config.narrow_passage_cost_value if distance_m <= narrow_m else 0,
                            min(
                                self.occupied_threshold - 1,
                                int(round(risk * self.config.traversability_risk_weight)),
                            ),
                        )
                        state = "high_cost"
                    else:
                        state = "normal"
                    if change.value(x, y) == "newly_blocked":
                        adapted, state = 100, "blocked"
                        blocked.add(cell)
                        observed_free.discard(cell)
                data.append(adapted)
                states.append(state)

        grid = OccupancyGrid(
            live.width,
            live.height,
            live.resolution,
            live.origin,
            tuple(data),
            frame_id=live.frame_id,
        )
        return TraversabilityMap(
            grid,
            clearance,
            tuple(states),
            frozenset(observed_free),
            frozenset(blocked),
            frozenset(prior_reference),
        )
