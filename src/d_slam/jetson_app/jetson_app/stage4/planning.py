from __future__ import annotations

import math
from collections import deque
from dataclasses import replace
from typing import Any, Sequence

from ..domain import OccupancyGrid, Point2D, RiskZone, RoutePlan
from ..planning import NoRouteError
from ..planning.astar import point_in_polygon
from .models import AlignmentResult, ChangeMap, Stage4Config, TraversabilityMap


def route_distinctness(first: RoutePlan, second: RoutePlan, grid: OccupancyGrid) -> float:
    def cells(route: RoutePlan) -> set[tuple[int, int]]:
        result = set()
        for point in route.points:
            try:
                result.add(grid.world_to_cell(point))
            except IndexError:
                pass
        return result

    first_cells, second_cells = cells(first), cells(second)
    if not first_cells and not second_cells:
        return 0.0
    return 1.0 - len(first_cells & second_cells) / max(1, len(first_cells | second_cells))


def _corridor_grid(base: OccupancyGrid, routes: Sequence[RoutePlan], radius: int) -> OccupancyGrid:
    if not routes:
        return base
    data = list(base.data)
    for route in routes:
        for point in route.points[1:-1]:
            try:
                cx, cy = base.world_to_cell(point)
            except IndexError:
                continue
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < base.width and 0 <= y < base.height:
                        data[y * base.width + x] = 100
    for route in routes:
        for point in (route.start, route.goal):
            try:
                x, y = base.world_to_cell(point)
                data[y * base.width + x] = base.value(x, y)
            except IndexError:
                pass
    return OccupancyGrid(
        base.width, base.height, base.resolution, base.origin, tuple(data), base.frame_id
    )


def plan_distinct_routes(
    planner: Any,
    traversability: TraversabilityMap,
    start: Point2D,
    goal: Point2D,
    risks: Sequence[RiskZone],
    *,
    map_version: int,
    target_id: str | None,
    config: Stage4Config,
) -> tuple[RoutePlan, ...]:
    accepted: list[RoutePlan] = []
    for _ in range(max(config.route_candidate_count * 3, config.route_candidate_count)):
        grid = _corridor_grid(
            traversability.grid, accepted, config.route_corridor_radius_cells
        )
        try:
            route = planner.plan(
                grid,
                start,
                goal,
                risks,
                map_version=map_version,
                target_id=target_id,
            )
        except NoRouteError:
            break
        if any(
            route_distinctness(route, existing, traversability.grid)
            < config.route_distinctness_min
            for existing in accepted
        ):
            break
        accepted.append(
            replace(route, route_id=f"{route.route_id}-candidate-{len(accepted) + 1}")
        )
        if len(accepted) >= config.route_candidate_count:
            break
    return tuple(accepted)


def route_evaluation(
    route: RoutePlan,
    traversability: TraversabilityMap,
    change: ChangeMap,
    *,
    alignment_confidence: float,
    config: Stage4Config,
) -> dict[str, Any]:
    unknown = changed_near = 0
    clearances: list[float] = []
    changed = set(change.cells("newly_blocked"))
    for point in route.points:
        try:
            cell = traversability.grid.world_to_cell(point)
        except IndexError:
            continue
        unknown += int(traversability.grid.value(*cell) == -1)
        clearances.append(traversability.clearance(cell))
        changed_near += int(any(abs(cell[0] - x) <= 1 and abs(cell[1] - y) <= 1 for x, y in changed))
    count = max(1, len(route.points))
    unknown_ratio = unknown / count
    change_ratio = changed_near / count
    min_clearance = min(clearances, default=0.0)
    score = (
        route.total_distance * config.route_score_distance_weight
        + route.risk_cost * config.route_score_risk_weight
        + unknown_ratio * config.route_score_unknown_weight
        + change_ratio * config.route_score_change_weight
        + (1.0 / max(0.05, min_clearance)) * config.route_score_clearance_weight
    )
    confidence = max(
        0.0,
        min(1.0, alignment_confidence * (1.0 - min(0.8, unknown_ratio + change_ratio))),
    )
    return {
        "route_id": route.route_id,
        "target_id": route.target_id,
        "total_distance": round(route.total_distance, 6),
        "risk_cost": round(route.risk_cost, 6),
        "unknown_ratio": round(unknown_ratio, 6),
        "newly_blocked_proximity_ratio": round(change_ratio, 6),
        "minimum_clearance_m": round(min_clearance, 6),
        "score": round(score, 6),
        "estimated_confidence": round(confidence, 6),
    }


def _reachable(traversability: TraversabilityMap, starts: Sequence[Point2D]) -> set[tuple[int, int]]:
    grid = traversability.grid
    reached: set[tuple[int, int]] = set()
    queue: deque[tuple[int, int]] = deque()
    for point in starts:
        try:
            cell = grid.world_to_cell(point)
        except IndexError:
            continue
        if cell in traversability.observed_free_cells and cell not in traversability.blocked_cells:
            reached.add(cell)
            queue.append(cell)
    while queue:
        x, y = queue.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            cell = (x + dx, y + dy)
            if (
                cell in reached
                or cell not in traversability.observed_free_cells
                or cell in traversability.blocked_cells
            ):
                continue
            reached.add(cell)
            queue.append(cell)
    return reached


def safe_zone_candidates(
    traversability: TraversabilityMap,
    entrances: Sequence[Point2D],
    risks: Sequence[RiskZone],
    routes: Sequence[RoutePlan],
    change: ChangeMap,
    *,
    alignment: AlignmentResult,
    config: Stage4Config,
) -> tuple[tuple[Point2D, ...], tuple[dict[str, Any], ...]]:
    if not alignment.automatic_map_alignment or config.safe_zone_count == 0:
        return (), ()
    grid = traversability.grid
    changed = set(change.cells("newly_blocked"))
    route_points = [point for route in routes for point in route.points]
    scored = []
    for cell in sorted(_reachable(traversability, entrances)):
        clearance = traversability.clearance(cell)
        if clearance < config.safe_zone_min_clearance_m:
            continue
        point = grid.cell_to_world(cell)
        if any(
            risk.severity >= config.safe_zone_risk_block_severity
            and point_in_polygon(point, risk.polygon)
            for risk in risks
        ):
            continue
        risk_distance = min(
            (math.hypot(point.x - risk.center.x, point.y - risk.center.y) for risk in risks),
            default=3.0,
        )
        block_distance = (
            min(math.hypot(cell[0] - x, cell[1] - y) * grid.resolution for x, y in changed)
            if changed
            else config.safe_zone_change_distance_m * 2
        )
        if block_distance < config.safe_zone_change_distance_m:
            continue
        entrance_distance = min(
            (math.hypot(point.x - item.x, point.y - item.y) for item in entrances),
            default=0.0,
        )
        route_distance = min(
            (math.hypot(point.x - item.x, point.y - item.y) for item in route_points),
            default=0.0,
        )
        score = (
            clearance
            + min(block_distance, 3.0)
            + 0.5 * min(risk_distance, 3.0)
            - 0.05 * entrance_distance
            - 0.05 * route_distance
        )
        scored.append((score, cell, {
            "clearance_m": round(clearance, 6),
            "newly_blocked_distance_m": round(block_distance, 6),
            "risk_distance_m": round(risk_distance, 6),
            "entrance_distance_m": round(entrance_distance, 6),
            "route_distance_m": round(route_distance, 6),
            "observed": True,
        }))

    chosen: list[Point2D] = []
    metadata = []
    for score, cell, values in sorted(scored, key=lambda item: (-item[0], item[1][1], item[1][0])):
        point = grid.cell_to_world(cell)
        if any(math.hypot(point.x - item.x, point.y - item.y) < config.safe_zone_spacing_m for item in chosen):
            continue
        chosen.append(point)
        metadata.append({"slam_position": point.to_dict(), "score": round(score, 6), **values})
        if len(chosen) >= config.safe_zone_count:
            break
    return tuple(chosen), tuple(metadata)
