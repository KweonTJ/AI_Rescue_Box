"""Deterministic A* over occupancy grids with conservative unknown handling."""

from __future__ import annotations

import heapq
import math
from typing import Sequence

from ..domain import OccupancyGrid, Point2D, RiskZone, RoutePlan, utc_now
from ..providers.base import RoutePlanningProvider


class NoRouteError(RuntimeError):
    pass


def _point_on_segment(point: Point2D, first: Point2D, second: Point2D) -> bool:
    cross = (point.y - first.y) * (second.x - first.x) - (point.x - first.x) * (
        second.y - first.y
    )
    if abs(cross) > 1e-9:
        return False
    return (
        min(first.x, second.x) - 1e-9 <= point.x <= max(first.x, second.x) + 1e-9
        and min(first.y, second.y) - 1e-9 <= point.y <= max(first.y, second.y) + 1e-9
    )


def point_in_polygon(point: Point2D, polygon: Sequence[Point2D]) -> bool:
    if len(polygon) == 1:
        return math.hypot(point.x - polygon[0].x, point.y - polygon[0].y) < 1e-9
    inside = False
    for index, first in enumerate(polygon):
        second = polygon[(index + 1) % len(polygon)]
        if _point_on_segment(point, first, second):
            return True
        if (first.y > point.y) != (second.y > point.y):
            intersection_x = (second.x - first.x) * (point.y - first.y) / (
                second.y - first.y
            ) + first.x
            if point.x < intersection_x:
                inside = not inside
    return inside


class AStarRoutePlanner(RoutePlanningProvider):
    def __init__(
        self,
        *,
        occupied_threshold: int = 65,
        allow_unknown: bool = False,
        unknown_cost: float = 100.0,
        risk_weight: float = 25.0,
        block_risk_at: float = 0.8,
        allow_diagonal: bool = False,
    ) -> None:
        self.occupied_threshold = occupied_threshold
        self.allow_unknown = allow_unknown
        self.unknown_cost = unknown_cost
        self.risk_weight = risk_weight
        self.block_risk_at = block_risk_at
        self.allow_diagonal = allow_diagonal

    def _risk_at(self, point: Point2D, risks: Sequence[RiskZone]) -> float:
        severity = 0.0
        for risk in risks:
            if risk.state.value == "unknown" and self.allow_unknown:
                continue
            if point_in_polygon(point, risk.polygon):
                severity = max(severity, risk.severity)
        return severity

    def plan(
        self,
        grid: OccupancyGrid,
        start: Point2D,
        goal: Point2D,
        risks: Sequence[RiskZone],
        *,
        map_version: int,
        target_id: str | None = None,
    ) -> RoutePlan:
        try:
            start_cell = grid.world_to_cell(start)
            goal_cell = grid.world_to_cell(goal)
        except IndexError as error:
            raise NoRouteError("start or goal is outside occupancy grid") from error

        def cell_cost(cell: tuple[int, int]) -> tuple[float, float, bool] | None:
            value = grid.value(*cell)
            if value >= self.occupied_threshold:
                return None
            unknown = value == -1
            if unknown and not self.allow_unknown:
                return None
            point = grid.cell_to_world(cell)
            risk = self._risk_at(point, risks)
            if risk >= self.block_risk_at:
                return None
            extra = (self.unknown_cost if unknown else max(value, 0) / 100.0) + (
                risk * self.risk_weight
            )
            return 1.0 + extra, risk * self.risk_weight, unknown

        if cell_cost(start_cell) is None or cell_cost(goal_cell) is None:
            raise NoRouteError("start or goal is blocked, risky, or unknown")

        neighbor_steps = [(0, -1, 1.0), (-1, 0, 1.0), (1, 0, 1.0), (0, 1, 1.0)]
        if self.allow_diagonal:
            diagonal = math.sqrt(2.0)
            neighbor_steps += [
                (-1, -1, diagonal),
                (1, -1, diagonal),
                (-1, 1, diagonal),
                (1, 1, diagonal),
            ]

        frontier: list[tuple[float, float, int, int]] = []
        heapq.heappush(frontier, (0.0, 0.0, start_cell[1], start_cell[0]))
        came_from: dict[tuple[int, int], tuple[int, int] | None] = {start_cell: None}
        cost_so_far = {start_cell: 0.0}
        risk_so_far = {start_cell: 0.0}
        unknown_so_far = {start_cell: grid.value(*start_cell) == -1}

        while frontier:
            _, current_cost, current_y, current_x = heapq.heappop(frontier)
            current = (current_x, current_y)
            if current_cost != cost_so_far.get(current):
                continue
            if current == goal_cell:
                break
            for dx, dy, distance in neighbor_steps:
                neighbor = (current_x + dx, current_y + dy)
                if not (0 <= neighbor[0] < grid.width and 0 <= neighbor[1] < grid.height):
                    continue
                evaluated = cell_cost(neighbor)
                if evaluated is None:
                    continue
                traversal, risk_cost, unknown = evaluated
                new_cost = current_cost + traversal * distance
                old_cost = cost_so_far.get(neighbor)
                if old_cost is not None and new_cost >= old_cost - 1e-12:
                    continue
                cost_so_far[neighbor] = new_cost
                risk_so_far[neighbor] = risk_so_far[current] + risk_cost * distance
                unknown_so_far[neighbor] = unknown_so_far[current] or unknown
                came_from[neighbor] = current
                heuristic = abs(goal_cell[0] - neighbor[0]) + abs(
                    goal_cell[1] - neighbor[1]
                )
                heapq.heappush(
                    frontier,
                    (new_cost + heuristic, new_cost, neighbor[1], neighbor[0]),
                )

        if goal_cell not in came_from:
            raise NoRouteError("no traversable route exists")
        cells = []
        current: tuple[int, int] | None = goal_cell
        while current is not None:
            cells.append(current)
            current = came_from[current]
        cells.reverse()
        points = tuple(grid.cell_to_world(cell) for cell in cells)
        distance = sum(
            math.hypot(second.x - first.x, second.y - first.y)
            for first, second in zip(points, points[1:])
        )
        return RoutePlan(
            route_id=(
                f"route-{map_version:04d}-{start_cell[0]}-{start_cell[1]}-"
                f"{goal_cell[0]}-{goal_cell[1]}"
            ),
            start=start,
            goal=goal,
            points=points,
            total_distance=distance,
            risk_cost=risk_so_far[goal_cell],
            contains_unknown=unknown_so_far[goal_cell],
            created_at=utc_now(),
            map_version=map_version,
            target_id=target_id,
        )
