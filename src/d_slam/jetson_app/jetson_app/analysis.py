"""Orchestrate one explainable analysis pass into a semantic_result artifact."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .alignment import PriorSlamAlignmentEvaluator
from .domain import (
    MissionManifest,
    PersonCandidate,
    Point2D,
    RiskZone,
    RoutePlan,
    SemanticResult,
    mean_confidence,
)
from .planning import NoRouteError
from .planning.astar import point_in_polygon
from .providers.base import (
    ProviderMode,
    RiskAssessmentProvider,
    RoutePlanningProvider,
    SlamProvider,
    TeamRecommendationProvider,
)


@dataclass(frozen=True)
class AnalysisReport:
    result: SemanticResult
    unreachable_candidate_ids: tuple[str, ...]


class AnalysisPipeline:
    def __init__(
        self,
        *,
        slam: SlamProvider,
        risk: RiskAssessmentProvider,
        route: RoutePlanningProvider,
        teams: TeamRecommendationProvider,
        alignment: PriorSlamAlignmentEvaluator | None = None,
    ) -> None:
        self.slam = slam
        self.risk = risk
        self.route = route
        self.teams = teams
        self.alignment = alignment or PriorSlamAlignmentEvaluator()

    @staticmethod
    def safe_waiting_points(
        entrances: Sequence[Point2D], risks: Sequence[RiskZone]
    ) -> tuple[Point2D, ...]:
        """Entrances are the only initial waiting candidates; no place is invented."""

        safe = []
        for entrance in entrances:
            if all(
                not point_in_polygon(entrance, zone.polygon) or zone.severity < 0.8
                for zone in risks
            ):
                safe.append(entrance)
        return tuple(safe)

    def run(
        self,
        *,
        mission: MissionManifest,
        candidates: Sequence[PersonCandidate],
        result_version: int,
        priorities: dict[str, int] | None = None,
    ) -> AnalysisReport:
        snapshot = self.slam.snapshot()
        map_alignment = self.alignment.evaluate(mission, snapshot)
        risks = tuple(self.risk.assess(snapshot))
        routes: list[RoutePlan] = []
        unreachable = []
        for candidate in sorted(candidates, key=lambda item: item.detection_id):
            if candidate.map_position is None:
                unreachable.append(candidate.detection_id)
                continue
            best: RoutePlan | None = None
            for entrance in mission.entrances:
                try:
                    planned = self.route.plan(
                        snapshot.occupancy_grid,
                        entrance,
                        candidate.map_position,
                        risks,
                        map_version=snapshot.map_version,
                        target_id=candidate.detection_id,
                    )
                except NoRouteError:
                    continue
                score = (planned.risk_cost, planned.total_distance, planned.route_id)
                if best is None or score < (
                    best.risk_cost,
                    best.total_distance,
                    best.route_id,
                ):
                    best = planned
            if best is None:
                unreachable.append(candidate.detection_id)
            else:
                routes.append(best)

        waiting_points = self.safe_waiting_points(mission.entrances, risks)
        recommendations = tuple(
            self.teams.recommend(
                team_count=mission.available_teams,
                rescuer_count=mission.available_rescuers,
                candidates=candidates,
                routes=routes,
                waiting_points=waiting_points,
                priorities=priorities,
            )
        )
        confidences = [item.confidence for item in candidates]
        confidences.extend(item.confidence for item in risks)
        confidences.extend(item.confidence for item in recommendations)
        provider_mode = self.slam.status().mode
        analysis_mode = (
            "mock"
            if getattr(provider_mode, "value", provider_mode) == ProviderMode.MOCK.value
            else "real"
        )
        result = SemanticResult(
            mission_id=mission.mission_id,
            base_map_version=mission.mission_version,
            result_version=result_version,
            coordinate_frame=mission.coordinate_frame,
            robot_pose=snapshot.robot_pose,
            trajectory=snapshot.trajectory,
            victim_candidates=tuple(candidates),
            risks=risks,
            routes=tuple(routes),
            recommendations=recommendations,
            slam_map_version=snapshot.map_version,
            obstacles=tuple(
                zone.polygon
                for zone in risks
                if zone.risk_type == "obstacle_candidate"
            ),
            explored_areas=snapshot.explored_areas,
            unknown_areas=snapshot.unknown_areas,
            safe_waiting_points=waiting_points,
            map_alignment=map_alignment,
            confidence=mean_confidence(confidences, default=0.0),
            source=(
                "jetson_mock_analysis"
                if analysis_mode == "mock"
                else "jetson_sensor_analysis"
            ),
            analysis_mode=analysis_mode,
        )
        return AnalysisReport(result, tuple(unreachable))
