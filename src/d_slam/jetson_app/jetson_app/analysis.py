"""Orchestrate one explainable analysis pass into a semantic_result artifact."""

from __future__ import annotations

import copy
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

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
from .perception.hazards import fuse_ai_with_sensor_risks
from .planning import NoRouteError
from .planning.astar import point_in_polygon
from .providers.base import (
    ProviderMode,
    RiskAssessmentProvider,
    RoutePlanningProvider,
    SlamProvider,
    TeamRecommendationProvider,
)
from .stage4 import (
    Stage4Artifacts,
    Stage4Processor,
    plan_distinct_routes,
    route_distinctness,
    route_evaluation,
    safe_zone_candidates,
)
from .stage4.return_routes import (
    plan_stage3_return_routes,
    plan_stage4_return_routes,
)


@dataclass(frozen=True)
class AnalysisReport:
    result: SemanticResult
    unreachable_candidate_ids: tuple[str, ...]
    stage4_artifacts: Stage4Artifacts | None = None
    return_routes: tuple[Mapping[str, Any], ...] = ()

    def to_semantic_dict(self) -> dict[str, Any]:
        value = self.result.to_dict()
        value["return_routes"] = [copy.deepcopy(dict(item)) for item in self.return_routes]
        enriched = []
        for raw in value.get("risk_zones", []):
            item = copy.deepcopy(dict(raw))
            source = str(item.get("source", "")).strip()
            rationale = str(item.get("rationale", "")).strip()
            item.setdefault("evidence", {"sources": [part for part in source.split("+") if part], "rationale": rationale})
            enriched.append(item)
        value["risk_zones"] = enriched
        return value


class AnalysisPipeline:
    def __init__(self, *, slam: SlamProvider, risk: RiskAssessmentProvider, route: RoutePlanningProvider, teams: TeamRecommendationProvider, alignment: PriorSlamAlignmentEvaluator | None = None, mission_transform: ProvisionalMissionTransform | None = None, stage4: Stage4Processor | None = None, confirmation_observations: int = 2) -> None:
        if confirmation_observations < 2:
            raise ValueError("confirmation_observations must be at least two")
        self.slam = slam
        self.risk = risk
        self.route = route
        self.teams = teams
        self.alignment = alignment or PriorSlamAlignmentEvaluator()
        self.mission_transform = mission_transform or ProvisionalMissionTransform()
        self.stage4 = stage4
        self.confirmation_observations = confirmation_observations

    @staticmethod
    def safe_waiting_points(entrances: Sequence[Point2D], risks: Sequence[RiskZone]) -> tuple[Point2D, ...]:
        return tuple(entrance for entrance in entrances if all(not point_in_polygon(entrance, zone.polygon) or zone.severity < 0.8 for zone in risks))

    @staticmethod
    def _candidate_to_mission(candidate: PersonCandidate, transform: RigidMissionTransform) -> PersonCandidate:
        position = transform.slam_to_mission_point(candidate.map_position) if candidate.map_position is not None else None
        return replace(candidate, map_position=position)

    @staticmethod
    def _risk_to_mission(risk: RiskZone, transform: RigidMissionTransform) -> RiskZone:
        return replace(risk, polygon=tuple(transform.slam_to_mission_point(point) for point in risk.polygon))

    @staticmethod
    def _route_to_mission(route: RoutePlan, transform: RigidMissionTransform) -> RoutePlan:
        return replace(route, start=transform.slam_to_mission_point(route.start), goal=transform.slam_to_mission_point(route.goal), points=tuple(transform.slam_to_mission_point(point) for point in route.points))

    @staticmethod
    def _return_route_to_mission(route: Mapping[str, Any], transform: RigidMissionTransform) -> dict[str, Any]:
        value = copy.deepcopy(dict(route))
        def converted(raw: Mapping[str, Any]) -> dict[str, float]:
            mapped = transform.slam_to_mission_point(Point2D(float(raw["x"]), float(raw["y"])))
            return {"x": mapped.x, "y": mapped.y}
        for key in ("start", "goal"):
            raw = value.get(key)
            if isinstance(raw, Mapping):
                value[key] = converted(raw)
        points = value.get("points")
        if isinstance(points, Sequence) and not isinstance(points, (str, bytes)):
            value["points"] = [converted(item) for item in points if isinstance(item, Mapping)]
        return value

    @staticmethod
    def _recommendation_to_mission(recommendation: TeamRecommendation, transform: RigidMissionTransform) -> TeamRecommendation:
        return replace(recommendation, position=transform.slam_to_mission_point(recommendation.position))

    def _stage3_routes(self, *, grid, entrances: Sequence[Point2D], candidates: Sequence[PersonCandidate], risks: Sequence[RiskZone], map_version: int) -> tuple[list[RoutePlan], list[str]]:
        routes, unreachable = [], []
        for candidate in sorted(candidates, key=lambda item: item.detection_id):
            if candidate.map_position is None:
                unreachable.append(candidate.detection_id)
                continue
            best = None
            for entrance in entrances:
                try:
                    planned = self.route.plan(grid, entrance, candidate.map_position, risks, map_version=map_version, target_id=candidate.detection_id)
                except NoRouteError:
                    continue
                score = (planned.risk_cost, planned.total_distance, planned.route_id)
                if best is None or score < (best.risk_cost, best.total_distance, best.route_id):
                    best = planned
            if best is None:
                unreachable.append(candidate.detection_id)
            else:
                routes.append(best)
        return routes, unreachable

    def _stage4_routes(self, *, artifacts: Stage4Artifacts, entrances: Sequence[Point2D], candidates: Sequence[PersonCandidate], risks: Sequence[RiskZone], map_version: int) -> tuple[list[RoutePlan], list[RoutePlan], list[str], tuple[dict, ...]]:
        published, best_for_teams, unreachable, evaluations = [], [], [], []
        config = self.stage4.config if self.stage4 is not None else None
        assert config is not None
        for candidate in sorted(candidates, key=lambda item: item.detection_id):
            if candidate.map_position is None:
                unreachable.append(candidate.detection_id)
                continue
            candidate_routes = []
            planning_risks = tuple(risk for risk in risks if risk.risk_type not in {"obstacle_candidate", "unknown_area"})
            for entrance in entrances:
                for route in plan_distinct_routes(self.route, artifacts.traversability, entrance, candidate.map_position, planning_risks, map_version=map_version, target_id=candidate.detection_id, config=config):
                    evaluation = route_evaluation(route, artifacts.traversability, artifacts.change, alignment_confidence=artifacts.alignment.confidence, config=config)
                    candidate_routes.append((route, evaluation))
            candidate_routes.sort(key=lambda item: (item[1]["score"], item[0].risk_cost, item[0].total_distance, item[0].route_id))
            selected = []
            for route, evaluation in candidate_routes:
                if any(route_distinctness(route, existing[0], artifacts.traversability.grid) < config.route_distinctness_min for existing in selected):
                    continue
                selected.append((route, evaluation))
                if len(selected) >= config.route_candidate_count:
                    break
            if not selected:
                unreachable.append(candidate.detection_id)
                continue
            best_for_teams.append(selected[0][0])
            for rank, (route, evaluation) in enumerate(selected, start=1):
                ranked = replace(route, route_id=f"{route.route_id}-rank-{rank}")
                evaluations.append({**evaluation, "route_id": ranked.route_id, "rank": rank})
                published.append(ranked)
        return published, best_for_teams, unreachable, tuple(evaluations)

    def run(self, *, mission: MissionManifest, candidates: Sequence[PersonCandidate], result_version: int, priorities: dict[str, int] | None = None, prior_map_path: Path | None = None) -> AnalysisReport:
        snapshot = self.slam.snapshot()
        provider_mode = self.slam.status().mode
        is_mock = getattr(provider_mode, "value", provider_mode) == ProviderMode.MOCK.value
        slam_start_pose = snapshot.trajectory[0] if snapshot.trajectory else snapshot.robot_pose
        initial_transform = ProvisionalMissionTransform.identity_for_mock() if is_mock else self.mission_transform.resolve(mission, slam_start_pose)
        risks_slam = fuse_ai_with_sensor_risks(tuple(self.risk.assess(snapshot)))
        stage4_artifacts = None
        transform = initial_transform
        if not is_mock and self.stage4 is not None and prior_map_path is not None:
            stage4_artifacts = self.stage4.prepare(mission=mission, prior_map_path=Path(prior_map_path), snapshot=snapshot, initial=initial_transform, risks=risks_slam)
            transform = stage4_artifacts.alignment.transform
        slam_entrances = tuple(transform.mission_to_slam_point(point) for point in mission.entrances)
        if stage4_artifacts is None:
            routes_slam, unreachable = self._stage3_routes(grid=snapshot.occupancy_grid, entrances=slam_entrances, candidates=candidates, risks=risks_slam, map_version=snapshot.map_version)
            best_routes_slam = list(routes_slam)
            waiting_slam = self.safe_waiting_points(slam_entrances, risks_slam)
            return_routes_slam = plan_stage3_return_routes(self.route, snapshot.occupancy_grid, candidates, slam_entrances, waiting_slam, risks_slam, map_version=snapshot.map_version)
            route_evaluations, safe_evaluations = (), ()
        else:
            routes_slam, best_routes_slam, unreachable, route_evaluations = self._stage4_routes(artifacts=stage4_artifacts, entrances=slam_entrances, candidates=candidates, risks=risks_slam, map_version=snapshot.map_version)
            stage4_safe_risks = tuple(risk for risk in risks_slam if risk.risk_type not in {"obstacle_candidate", "unknown_area"})
            waiting_slam, safe_evaluations = safe_zone_candidates(stage4_artifacts.traversability, slam_entrances, stage4_safe_risks, routes_slam, stage4_artifacts.change, alignment=stage4_artifacts.alignment, config=self.stage4.config)
            return_routes_slam = plan_stage4_return_routes(self.route, stage4_artifacts, candidates, slam_entrances, waiting_slam, risks_slam, map_version=snapshot.map_version, config=self.stage4.config)
            stage4_artifacts = replace(stage4_artifacts, route_evaluations=route_evaluations, safe_zone_evaluations=safe_evaluations)
        recommendations_slam = tuple(self.teams.recommend(team_count=mission.available_teams, rescuer_count=mission.available_rescuers, candidates=candidates, routes=best_routes_slam, waiting_points=waiting_slam, priorities=priorities))
        mission_candidates = tuple(self._candidate_to_mission(candidate, transform) for candidate in candidates)
        confirmed = tuple(replace(candidate, host_status="confirmed") for candidate in mission_candidates if candidate.map_position is not None and candidate.depth_valid and candidate.observation_count >= self.confirmation_observations)
        risks = tuple(self._risk_to_mission(risk, transform) for risk in risks_slam)
        routes = tuple(self._route_to_mission(route, transform) for route in routes_slam)
        return_routes = tuple(self._return_route_to_mission(route, transform) for route in return_routes_slam)
        recommendations = tuple(self._recommendation_to_mission(item, transform) for item in recommendations_slam)
        waiting_points = tuple(transform.slam_to_mission_point(point) for point in waiting_slam)
        explored_areas = tuple(tuple(transform.slam_to_mission_point(point) for point in polygon) for polygon in snapshot.explored_areas)
        unknown_areas = tuple(tuple(transform.slam_to_mission_point(point) for point in polygon) for polygon in snapshot.unknown_areas)
        if stage4_artifacts is None:
            map_alignment = {**transform.metadata(), "prior_live_extent_sanity": self.alignment.evaluate(mission, snapshot)}
        else:
            map_alignment = {**stage4_artifacts.alignment.metadata(), "stage4": stage4_artifacts.metadata(include_change_cells=False)}
        confidences = [item.confidence for item in mission_candidates]
        confidences.extend(item.confidence for item in risks)
        confidences.extend(item.confidence for item in recommendations)
        confidences.extend(float(item.get("confidence", 0.0)) for item in return_routes)
        if stage4_artifacts is not None:
            confidences.append(stage4_artifacts.alignment.confidence)
        analysis_mode = "mock" if is_mock else "real"
        result = SemanticResult(mission_id=mission.mission_id, base_map_version=mission.mission_version, result_version=result_version, coordinate_frame="mission_map", robot_pose=transform.slam_to_mission_pose(snapshot.robot_pose), trajectory=tuple(transform.slam_to_mission_pose(pose) for pose in snapshot.trajectory), victim_candidates=mission_candidates, confirmed_victims=confirmed, risks=risks, routes=routes, recommendations=recommendations, slam_map_version=snapshot.map_version, obstacles=tuple(zone.polygon for zone in risks if zone.risk_type in {"obstacle_candidate", "debris", "blocked_passage"}), explored_areas=explored_areas, unknown_areas=unknown_areas, safe_waiting_points=waiting_points, map_alignment=map_alignment, confidence=mean_confidence(confidences, default=0.0), source="jetson_mock_analysis" if analysis_mode == "mock" else "jetson_sensor_analysis", analysis_mode=analysis_mode)
        object.__setattr__(result, "_return_routes", return_routes)
        return AnalysisReport(result=result, unreachable_candidate_ids=tuple(unreachable), stage4_artifacts=stage4_artifacts, return_routes=return_routes)
