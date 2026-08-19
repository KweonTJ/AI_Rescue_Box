"""Deterministic, explainable rescue-team placement recommendations."""

from __future__ import annotations

from typing import Sequence

from ..domain import PersonCandidate, Point2D, RoutePlan, TeamRecommendation
from ..providers.base import TeamRecommendationProvider


class RuleBasedTeamRecommendationProvider(TeamRecommendationProvider):
    def __init__(self, *, rescuers_per_team: int = 2) -> None:
        if rescuers_per_team < 1:
            raise ValueError("rescuers_per_team must be positive")
        self.rescuers_per_team = rescuers_per_team

    def recommend(
        self,
        *,
        team_count: int,
        rescuer_count: int,
        candidates: Sequence[PersonCandidate],
        routes: Sequence[RoutePlan],
        waiting_points: Sequence[Point2D],
        priorities: dict[str, int] | None = None,
    ) -> Sequence[TeamRecommendation]:
        if team_count < 0 or rescuer_count < 0:
            raise ValueError("team and rescuer counts cannot be negative")
        if team_count == 0:
            team_count = rescuer_count // self.rescuers_per_team
        priorities = priorities or {}
        routes_by_target = {route.target_id: route for route in routes if route.target_id}
        eligible = [
            candidate
            for candidate in candidates
            if candidate.map_position is not None and candidate.detection_id in routes_by_target
        ]
        eligible.sort(
            key=lambda candidate: (
                -priorities.get(candidate.detection_id, 0),
                routes_by_target[candidate.detection_id].risk_cost,
                routes_by_target[candidate.detection_id].total_distance,
                candidate.detection_id,
            )
        )
        recommendations = []
        for index in range(team_count):
            team_id = f"team-{index + 1:02d}"
            if index < len(eligible):
                candidate = eligible[index]
                route = routes_by_target[candidate.detection_id]
                confidence = max(
                    0.1,
                    min(1.0, candidate.confidence * (1.0 / (1.0 + route.risk_cost))),
                )
                recommendations.append(
                    TeamRecommendation(
                        team_id=team_id,
                        position=route.start,
                        victim_id=candidate.detection_id,
                        route_id=route.route_id,
                        estimated_distance=route.total_distance,
                        risk_cost=route.risk_cost,
                        rationale=(
                            "highest remaining victim priority, then lowest route risk "
                            "and travel distance"
                        ),
                        confidence=confidence,
                    )
                )
            else:
                if not waiting_points:
                    break
                waiting = waiting_points[
                    min(index - len(eligible), len(waiting_points) - 1)
                ]
                recommendations.append(
                    TeamRecommendation(
                        team_id=team_id,
                        position=waiting,
                        victim_id=None,
                        route_id=None,
                        estimated_distance=0.0,
                        risk_cost=0.0,
                        rationale="no reachable positioned victim; hold at safe waiting point",
                        confidence=0.7,
                    )
                )
        return tuple(recommendations)
