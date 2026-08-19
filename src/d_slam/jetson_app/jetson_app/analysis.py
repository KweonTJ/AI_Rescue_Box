"""Orchestrate one explainable analysis pass into a semantic_result artifact."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence

from .alignment import PriorSlamAlignmentEvaluator, ProvisionalMissionTransform, RigidMissionTransform
from .domain import (
    MissionManifest,
    PersonCandidate,
    Point2D,
    RiskZone,
    RoutePlan,
    SemanticResult,
    TeamRecommendation,
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
    """Keep planning in live SLAM coordinates, export only mission-map coordinates."""

    def __init__(
        self,
        *,
        slam: SlamProvider,
        risk: RiskAssessmentProvider,
        route: RoutePlanningProvider,
        teams: TeamRecommendationProvider,
        alignment: PriorSlamAlignmentEvaluator | None = None,
        mission_transform: ProvisionalMissionTransform | None = None,
        confirmation_observations: int = 2,
    ) -> None:
        if confirmation_observations < 2:
            raise ValueError("confirmation_observations must be at least two")
        self.slam = slam
        self.risk = risk
        self.route = route
        self.teams = teams
        self.alignment = alignment or PriorSlamAlignmentEvaluator()
        self.mission_transform = mission_transform or ProvisionalMissionTransform()
        self.confirmation_observations = confirmation_observations

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

    @staticmethod
    def _candidate_to_mission(
        candidate: PersonCandidate, transform: RigidMissionTransform
    ) -> PersonCandidate:
        position = (
            transform.slam_to_mission_point(candidate.map_position)
            if candidate.map_position is not None
            else None
        )
        return replace(candidate, map_position=position)

    @staticmethod
    def _risk_to_mission(
        risk: RiskZone, transform: RigidMissionTransform
    ) -> RiskZone:
        return replace(
            risk,
            polygon=tuple(transform.slam_to_mission_point(point) for point in risk.polygon),
        )

    @staticmethod
    def _route_to_mission(
        route: RoutePlan, transform: RigidMissionTransform
    ) -> RoutePlan:
        return replace(
            route,
            start=transform.slam_to_mission_point(route.start),
            goal=transform.slam_to_mission_point(route.goal),
            points=tuple(transform.slam_to_mission_point(point) for point in route.points),
        )

    @staticmethod
    def _recommendation_to_mission(
        recommendation: TeamRecommendation, transform: RigidMissionTransform
    ) -> TeamRecommendation:
        return replace(
            recommendation,
            position=transform.slam_to_mission_point(recommendation.position),
        )

    def run(
        self,
        *,
        mission: MissionManifest,
        candidates: Sequence[PersonCandidate],
        result_version: int,
        priorities: dict[str, int] | None = None,
    ) -> AnalysisReport:
        snapshot = self.slam.snapshot()
        provider_mode = self.slam.status().mode
        is_mock = (
            getattr(provider_mode, "value", provider_mode) == ProviderMode.MOCK.value
        )
        slam_start_pose = (
            snapshot.trajectory[0] if snapshot.trajectory else snapshot.robot_pose
        )
        transform = (
            ProvisionalMissionTransform.identity_for_mock()
            if is_mock
            else self.mission_transform.resolve(mission, slam_start_pose)
        )

        # The RTAB occupancy grid is never rotated/re-written for Stage 3.  Convert
        # mission entrances into the live SLAM frame, plan there, then transform
        # only the published result back into mission_map.
        slam_entrances = tuple(
            transform.mission_to_slam_point(point) for point in mission.entrances
        )
        risks_slam = tuple(self.risk.assess(snapshot))
        routes_slam: list[RoutePlan] = []
        unreachable = []
        for candidate in sorted(candidates, key=lambda item: item.detection_id):
            if candidate.map_position is None:
                unreachable.append(candidate.detection_id)
                continue
            best: RoutePlan | None = None
            for entrance in slam_entrances:
                try:
                    planned = self.route.plan(
                        snapshot.occupancy_grid,
                        entrance,
                        candidate.map_position,
                        risks_slam,
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
                routes_slam.append(best)

        waiting_slam = self.safe_waiting_points(slam_entrances, risks_slam)
        recommendations_slam = tuple(
            self.teams.recommend(
                team_count=mission.available_teams,
                rescuer_count=mission.available_rescuers,
                candidates=candidates,
                routes=routes_slam,
                waiting_points=waiting_slam,
                priorities=priorities,
            )
        )

        mission_candidates = tuple(
            self._candidate_to_mission(candidate, transform) for candidate in candidates
        )
        confirmed = tuple(
            replace(candidate, host_status="confirmed")
            for candidate in mission_candidates
            if candidate.map_position is not None
            and candidate.depth_valid
            and candidate.observation_count >= self.confirmation_observations
        )
        risks = tuple(self._risk_to_mission(risk, transform) for risk in risks_slam)
        routes = tuple(self._route_to_mission(route, transform) for route in routes_slam)
        recommendations = tuple(
            self._recommendation_to_mission(item, transform)
            for item in recommendations_slam
        )
        waiting_points = tuple(
            transform.slam_to_mission_point(point) for point in waiting_slam
        )
        explored_areas = tuple(
            tuple(transform.slam_to_mission_point(point) for point in polygon)
            for polygon in snapshot.explored_areas
        )
        unknown_areas = tuple(
            tuple(transform.slam_to_mission_point(point) for point in polygon)
            for polygon in snapshot.unknown_areas
        )
        map_alignment = {
            **transform.metadata(),
            "prior_live_extent_sanity": self.alignment.evaluate(mission, snapshot),
        }

        confidences = [item.confidence for item in mission_candidates]
        confidences.extend(item.confidence for item in risks)
        confidences.extend(item.confidence for item in recommendations)
        analysis_mode = "mock" if is_mock else "real"
        result = SemanticResult(
            mission_id=mission.mission_id,
            base_map_version=mission.mission_version,
            result_version=result_version,
            coordinate_frame="mission_map",
            robot_pose=transform.slam_to_mission_pose(snapshot.robot_pose),
            trajectory=tuple(
                transform.slam_to_mission_pose(pose) for pose in snapshot.trajectory
            ),
            victim_candidates=mission_candidates,
            confirmed_victims=confirmed,
            risks=risks,
            routes=routes,
            recommendations=recommendations,
            slam_map_version=snapshot.map_version,
            obstacles=tuple(
                zone.polygon
                for zone in risks
                if zone.risk_type == "obstacle_candidate"
            ),
            explored_areas=explored_areas,
            unknown_areas=unknown_areas,
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
