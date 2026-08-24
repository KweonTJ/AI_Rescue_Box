"""Independent return-route planning from victims to exits or Safe Zones."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Sequence

from ..domain import PersonCandidate, Point2D, RiskZone, RoutePlan
from ..planning import NoRouteError
from ..providers.base import RoutePlanningProvider
from .models import Stage4Artifacts, Stage4Config
from .planning import (
    plan_distinct_routes,
    route_distinctness,
    route_evaluation,
)


def _route_dict(
    route: RoutePlan,
    *,
    goal_type: str,
    rank: int,
    minimum_clearance: float,
    confidence: float,
) -> dict[str, Any]:
    value = route.to_dict()
    value.update(
        {
            "goal_type": goal_type,
            "minimum_clearance": max(0.0, float(minimum_clearance)),
            "confidence": max(0.0, min(1.0, float(confidence))),
            "rank": int(rank),
        }
    )
    return value


def plan_stage3_return_routes(
    planner: RoutePlanningProvider,
    grid,
    candidates: Sequence[PersonCandidate],
    entrances: Sequence[Point2D],
    safe_zones: Sequence[Point2D],
    risks: Sequence[RiskZone],
    *,
    map_version: int,
) -> tuple[dict[str, Any], ...]:
    """Plan fresh candidate→goal routes on the latest occupancy grid.

    This deliberately calls the planner again instead of reversing an entry route.
    """
    output: list[dict[str, Any]] = []
    for candidate in sorted(candidates, key=lambda item: item.detection_id):
        if candidate.map_position is None:
            continue
        proposed: list[tuple[RoutePlan, str]] = []
        destinations = [
            *(("entrance", point) for point in entrances),
            *(("safe_zone", point) for point in safe_zones),
        ]
        for goal_type, goal in destinations:
            try:
                route = planner.plan(
                    grid,
                    candidate.map_position,
                    goal,
                    risks,
                    map_version=map_version,
                    target_id=candidate.detection_id,
                )
            except NoRouteError:
                continue
            proposed.append((route, goal_type))
        proposed.sort(
            key=lambda item: (
                item[0].risk_cost,
                item[0].total_distance,
                item[1],
                item[0].route_id,
            )
        )
        for rank, (route, goal_type) in enumerate(proposed, start=1):
            route = replace(
                route,
                route_id=f"return-{candidate.detection_id}-{goal_type}-{rank}",
            )
            confidence = 1.0 / (1.0 + max(0.0, route.risk_cost))
            output.append(
                _route_dict(
                    route,
                    goal_type=goal_type,
                    rank=rank,
                    minimum_clearance=0.0,
                    confidence=confidence,
                )
            )
    return tuple(output)


def plan_stage4_return_routes(
    planner: RoutePlanningProvider,
    artifacts: Stage4Artifacts,
    candidates: Sequence[PersonCandidate],
    entrances: Sequence[Point2D],
    safe_zones: Sequence[Point2D],
    risks: Sequence[RiskZone],
    *,
    map_version: int,
    config: Stage4Config,
) -> tuple[dict[str, Any], ...]:
    """Plan and rank fresh return routes using current traversability and risk."""
    output: list[dict[str, Any]] = []
    planning_risks = tuple(
        risk
        for risk in risks
        if risk.risk_type not in {"obstacle_candidate", "unknown_area"}
    )
    for candidate in sorted(candidates, key=lambda item: item.detection_id):
        if candidate.map_position is None:
            continue
        proposed: list[tuple[RoutePlan, dict[str, Any], str]] = []
        destinations = [
            *(("entrance", point) for point in entrances),
            *(("safe_zone", point) for point in safe_zones),
        ]
        for goal_type, goal in destinations:
            routes = plan_distinct_routes(
                planner,
                artifacts.traversability,
                candidate.map_position,
                goal,
                planning_risks,
                map_version=map_version,
                target_id=candidate.detection_id,
                config=config,
            )
            for route in routes:
                evaluation = route_evaluation(
                    route,
                    artifacts.traversability,
                    artifacts.change,
                    alignment_confidence=artifacts.alignment.confidence,
                    config=config,
                )
                proposed.append((route, evaluation, goal_type))
        proposed.sort(
            key=lambda item: (
                item[1]["score"],
                item[0].risk_cost,
                item[0].total_distance,
                item[2],
                item[0].route_id,
            )
        )
        selected: list[tuple[RoutePlan, dict[str, Any], str]] = []
        for route, evaluation, goal_type in proposed:
            if any(
                route_distinctness(
                    route, existing[0], artifacts.traversability.grid
                )
                < config.route_distinctness_min
                and goal_type == existing[2]
                for existing in selected
            ):
                continue
            selected.append((route, evaluation, goal_type))
        for rank, (route, evaluation, goal_type) in enumerate(selected, start=1):
            ranked = replace(
                route,
                route_id=f"return-{candidate.detection_id}-{goal_type}-{rank}",
            )
            output.append(
                _route_dict(
                    ranked,
                    goal_type=goal_type,
                    rank=rank,
                    minimum_clearance=float(
                        evaluation.get("minimum_clearance_m", 0.0)
                    ),
                    confidence=float(
                        evaluation.get("estimated_confidence", 0.0)
                    ),
                )
            )
    return tuple(output)


__all__ = ["plan_stage3_return_routes", "plan_stage4_return_routes"]
