from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from host_app.map_editor import read_map_preview_metadata
from jetson_app.alignment import ProvisionalMissionTransform, RigidMissionTransform
from jetson_app.analysis import AnalysisPipeline
from jetson_app.api.stage4_service import Stage4JetsonApiService
from jetson_app.domain import (
    BoundingBox,
    CameraPoint,
    MissionManifest,
    ObservationState,
    OccupancyGrid,
    PersonCandidate,
    Point2D,
    Pose2D,
    RiskZone,
)
from jetson_app.mission import MissionManager
from jetson_app.planning import AStarRoutePlanner, RuleBasedTeamRecommendationProvider
from jetson_app.providers.base import ProviderMode, ProviderStatus, SlamProvider, SlamSnapshot
from jetson_app.risk import RuleBasedRiskAssessmentProvider
from jetson_app.stage2_submit import current_analysis_artifacts
from jetson_app.stage4 import (
    AlignmentResult,
    ChangeMap,
    ChangeMapBuilder,
    PriorLiveMapAligner,
    PriorMapReference,
    Stage4Config,
    Stage4Processor,
    TraversabilityBuilder,
    TraversabilityMap,
    plan_distinct_routes,
    route_distinctness,
    route_evaluation,
    safe_zone_candidates,
)

STAMP = "2026-08-20T00:00:00Z"


def _manifest(width: int, height: int, mpp: float = 0.1, mission_id: str = "stage4-test") -> MissionManifest:
    return MissionManifest.from_dict({
        "schema_version": "1.0",
        "mission_id": mission_id,
        "mission_version": 1,
        "artifact_version": 1,
        "mission_name": "Stage 4 deterministic map",
        "created_at": STAMP,
        "base_map_filename": "prior.png",
        "base_map_sha256": "0" * 64,
        "base_map_width": width,
        "base_map_height": height,
        "meters_per_pixel": mpp,
        "coordinate_transform": {
            "image_origin": {"x": 0.0, "y": float(height - 1)},
            "meters_per_pixel": mpp,
            "rotation_radians": 0.0,
            "invert_y": True,
            "frame_id": "mission_map",
        },
        "robot_start": {"x": 0.5, "y": 0.5, "yaw": 0.0},
        "entrances": [{"x": 0.5, "y": 0.5}],
        "available_teams": 1,
        "available_rescuers": 2,
        "coordinate_frame": "mission_map",
        "units": "meters",
        "source": "host",
        "confidence": 1.0,
    })


def _snapshot(grid: OccupancyGrid, map_version: int = 7) -> SlamSnapshot:
    return SlamSnapshot(
        occupancy_grid=grid,
        robot_pose=Pose2D(0.5, 0.5, 0.0),
        trajectory=(Pose2D(0.5, 0.5, 0.0),),
        explored_areas=(),
        unknown_areas=(),
        tracking_status="tracking",
        map_version=map_version,
        timestamp=STAMP,
    )


def _transform_grid_from_prior(
    prior: PriorMapReference,
    *,
    width: int,
    height: int,
    resolution: float,
    transform: RigidMissionTransform,
) -> OccupancyGrid:
    probe = OccupancyGrid(
        width,
        height,
        resolution,
        Point2D(0.0, 0.0),
        (0,) * (width * height),
        frame_id="map",
    )
    values = []
    for y in range(height):
        for x in range(width):
            state = prior.sample_mission(transform.slam_to_mission_point(probe.cell_to_world((x, y))))
            values.append(-1 if state == -1 else state)
    return OccupancyGrid(width, height, resolution, Point2D(0.0, 0.0), tuple(values), frame_id="map")


def test_bounded_alignment_recovers_known_transform_and_rejects_insufficient_evidence(tmp_path: Path):
    width = height = 60
    image_path = tmp_path / "prior.png"
    image = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(image)
    draw.line((13, 12, 13, 51), fill=0, width=2)
    draw.line((13, 45, 48, 45), fill=0, width=2)
    draw.line((36, 18, 52, 18), fill=0, width=2)
    image.save(image_path)
    mission = _manifest(width, height)
    prior = PriorMapReference.from_image(mission, image_path, dark_threshold=64, free_threshold=220)
    expected = RigidMissionTransform(0.40, -0.30, math.radians(5.0), "known", "known")
    grid = _transform_grid_from_prior(prior, width=60, height=60, resolution=0.1, transform=expected)
    config = Stage4Config(
        alignment_translation_search_m=0.8,
        alignment_translation_coarse_step_m=0.2,
        alignment_translation_fine_step_m=0.05,
        alignment_yaw_search_radians=math.radians(8),
        alignment_yaw_coarse_step_radians=math.radians(2),
        alignment_yaw_fine_step_radians=math.radians(1),
        alignment_min_confidence=0.60,
        alignment_min_overlap=0.60,
        alignment_min_coverage=0.50,
    )
    aligner = PriorLiveMapAligner(config)
    initial = RigidMissionTransform(0.15, -0.10, 0.0, "initial_anchor", "provisional")
    result = aligner.align(mission, prior, _snapshot(grid), initial)
    assert result.status == "aligned"
    assert result.automatic_map_alignment is True
    assert result.fallback is False
    assert result.confidence >= config.alignment_min_confidence
    assert result.transform.translation_x_m == pytest.approx(expected.translation_x_m, abs=0.11)
    assert result.transform.translation_y_m == pytest.approx(expected.translation_y_m, abs=0.11)
    assert result.transform.yaw_radians == pytest.approx(expected.yaw_radians, abs=math.radians(2.1))

    unknown = OccupancyGrid(20, 20, 0.1, Point2D(0, 0), (-1,) * 400, frame_id="map")
    failed = aligner.align(mission, prior, _snapshot(unknown, 8), initial)
    assert failed.status == "insufficient_evidence"
    assert failed.automatic_map_alignment is False
    assert failed.fallback is True
    assert failed.transform == initial
    failed_change = ChangeMapBuilder().build(prior, _snapshot(unknown, 8), failed)
    failed_traversability = TraversabilityBuilder(
        config, occupied_threshold=65, minimum_passage_width_m=0.2
    ).build(prior, _snapshot(unknown, 8), failed, failed_change)
    safe, _ = safe_zone_candidates(
        failed_traversability,
        (Point2D(0.5, 0.5),),
        (),
        (),
        failed_change,
        alignment=failed,
        config=config,
    )
    assert set(failed_change.classes) == {"not_observed"}
    assert safe == ()


def test_change_map_and_traversability_keep_live_observation_authoritative(tmp_path: Path):
    image_path = tmp_path / "prior.png"
    image = Image.new("L", (8, 8), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle((2, 2, 2, 5), fill=0)
    image.save(image_path)
    mission = _manifest(8, 8, 1.0)
    prior = PriorMapReference.from_image(mission, image_path, dark_threshold=64, free_threshold=220)
    probe = OccupancyGrid(8, 8, 1.0, Point2D(0, 0), (0,) * 64, frame_id="map")
    values = []
    free_cell = occupied_cell = None
    for y in range(8):
        for x in range(8):
            prior_value = prior.sample_mission(probe.cell_to_world((x, y)))
            values.append(100 if prior_value == 100 else 0)
            if prior_value == 0 and free_cell is None and 1 <= x <= 6 and 1 <= y <= 6:
                free_cell = (x, y)
            elif prior_value == 100 and occupied_cell is None:
                occupied_cell = (x, y)
    assert free_cell is not None and occupied_cell is not None
    unknown_cell = (6, 6)
    values[free_cell[1] * 8 + free_cell[0]] = 100
    values[occupied_cell[1] * 8 + occupied_cell[0]] = 0
    values[unknown_cell[1] * 8 + unknown_cell[0]] = -1
    live = OccupancyGrid(8, 8, 1.0, Point2D(0, 0), tuple(values), frame_id="map")
    alignment = AlignmentResult(
        RigidMissionTransform(0, 0, 0, "prior_live_alignment", "aligned"),
        "aligned", 0.9, 0.9, 0.9, 0.0, 0.9, "bounded_se2_prior_live",
        False, True, 1, 2, 63, 4,
    )
    change = ChangeMapBuilder().build(prior, _snapshot(live, 2), alignment)
    assert change.value(*free_cell) == "newly_blocked"
    assert change.value(*occupied_cell) == "cleared_or_opened"
    assert change.value(*unknown_cell) == "not_observed"
    assert change.metadata()["counts"]["not_observed"] >= 1
    assert "unchanged" in change.classes

    risk_cell = next(
        (cell for cell in ((6, 1), (6, 2), (5, 1), (5, 2)) if live.value(*cell) == 0),
        None,
    )
    assert risk_cell is not None
    risk_point = live.cell_to_world(risk_cell)
    risk = RiskZone(
        risk_id="risk-cost",
        risk_type="debris",
        polygon=(risk_point,),
        severity=0.5,
        confidence=0.9,
        rationale="deterministic test",
        source="test",
        observed_at=STAMP,
        state=ObservationState.OBSERVED,
    )
    config = Stage4Config(
        robot_clearance_m=0.1,
        safe_zone_min_clearance_m=0.1,
        traversability_risk_weight=60.0,
    )
    traversability = TraversabilityBuilder(
        config, occupied_threshold=65, minimum_passage_width_m=0.2
    ).build(prior, _snapshot(live, 2), alignment, change, (risk,))
    assert traversability.grid.value(*free_cell) == 100
    assert traversability.grid.value(*unknown_cell) == -1
    assert unknown_cell not in traversability.observed_free_cells
    assert occupied_cell in traversability.observed_free_cells
    assert 0 < traversability.grid.value(*risk_cell) < 65
    assert traversability.states[risk_cell[1] * 8 + risk_cell[0]] == "high_cost"


def test_multi_route_ranking_and_safe_zone_use_traversable_observed_space():
    width, height = 12, 9
    grid = OccupancyGrid(width, height, 1.0, Point2D(0, 0), (0,) * (width * height), frame_id="map")
    traversability = TraversabilityMap(
        grid=grid,
        clearance_m=(5.0,) * (width * height),
        states=("normal",) * (width * height),
        observed_free_cells=frozenset((x, y) for y in range(height) for x in range(width)),
        blocked_cells=frozenset(),
        prior_reference_cells=frozenset(),
    )
    change = ChangeMap(width, height, ("unchanged",) * (width * height), True, 1)
    config = Stage4Config(
        route_candidate_count=3,
        route_distinctness_min=0.15,
        robot_clearance_m=0.1,
        safe_zone_count=2,
        safe_zone_min_clearance_m=0.5,
        safe_zone_spacing_m=2.0,
        safe_zone_change_distance_m=0.5,
    )
    planner = AStarRoutePlanner()
    start, goal = Point2D(1.5, 4.5), Point2D(10.5, 4.5)
    routes = plan_distinct_routes(
        planner, traversability, start, goal, (), map_version=1, target_id="victim-1", config=config
    )
    assert 2 <= len(routes) <= 3
    for index, route in enumerate(routes):
        for other in routes[index + 1:]:
            assert route_distinctness(route, other, grid) >= config.route_distinctness_min
    evaluations = [
        route_evaluation(route, traversability, change, alignment_confidence=0.9, config=config)
        for route in routes
    ]
    assert all(item["score"] >= 0 for item in evaluations)
    assert all("minimum_clearance_m" in item for item in evaluations)
    alignment = AlignmentResult(
        RigidMissionTransform(0, 0, 0, "prior_live_alignment", "aligned"),
        "aligned", 0.9, 0.9, 0.9, 0.0, 0.9, "bounded_se2_prior_live",
        False, True, 1, 1, width * height, 10,
    )
    safe, safe_meta = safe_zone_candidates(
        traversability, (start,), (), routes, change, alignment=alignment, config=config
    )
    assert len(safe) == 2
    assert len(safe_meta) == 2
    assert all(item["observed"] for item in safe_meta)


class StaticRealSlam(SlamProvider):
    def __init__(self, snapshot: SlamSnapshot) -> None:
        self._snapshot = snapshot

    def status(self) -> ProviderStatus:
        return ProviderStatus("stage4 replay slam", ProviderMode.REAL, True, "ready")

    def snapshot(self) -> SlamSnapshot:
        return self._snapshot


def test_stage4_semantic_preview_and_stage2_artifact_compatibility(tmp_path: Path):
    width, height, mpp = 24, 16, 0.5
    prior_source = tmp_path / "prior.png"
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width - 1, height - 1), outline="black", width=1)
    draw.line((11, 3, 11, 11), fill="black", width=1)
    image.save(prior_source)
    digest = hashlib.sha256(prior_source.read_bytes()).hexdigest()
    manifest_value = {
        "schema_version": "1.0",
        "mission_id": "stage4-service",
        "mission_version": 1,
        "artifact_version": 1,
        "mission_name": "Stage 4 service integration",
        "created_at": STAMP,
        "base_map_filename": "prior.png",
        "base_map_sha256": digest,
        "base_map_width": width,
        "base_map_height": height,
        "meters_per_pixel": mpp,
        "coordinate_transform": {
            "image_origin": {"x": 0.0, "y": float(height - 1)},
            "meters_per_pixel": mpp,
            "rotation_radians": 0.0,
            "invert_y": True,
            "frame_id": "mission_map",
        },
        "robot_start": {"x": 1.25, "y": 1.25, "yaw": 0.0},
        "entrances": [{"x": 1.25, "y": 1.25}],
        "available_teams": 1,
        "available_rescuers": 2,
        "coordinate_frame": "mission_map",
        "units": "meters",
        "source": "host",
        "confidence": 1.0,
    }
    manifest_path = tmp_path / "mission_manifest.json"
    manifest_path.write_text(json.dumps(manifest_value), encoding="utf-8")
    manager = MissionManager(tmp_path / "missions")
    applied = manager.apply_mission(manifest_path, prior_source)
    assert manager.current_mission_ref() is None
    manager.set_current_mission("stage4-service", 1)
    mission = applied.manifest
    prior = PriorMapReference.from_image(mission, applied.base_map_path, dark_threshold=64, free_threshold=220)
    live = _transform_grid_from_prior(
        prior, width=width, height=height, resolution=mpp,
        transform=RigidMissionTransform(0, 0, 0, "known", "known"),
    )
    slam = StaticRealSlam(SlamSnapshot(
        occupancy_grid=live,
        robot_pose=Pose2D(1.25, 1.25, 0.0),
        trajectory=(Pose2D(1.25, 1.25, 0.0),),
        explored_areas=((Point2D(0, 0), Point2D(12, 0), Point2D(12, 8), Point2D(0, 8)),),
        unknown_areas=(),
        tracking_status="tracking",
        map_version=4,
        timestamp=STAMP,
    ))
    stage4_config = Stage4Config(
        alignment_translation_search_m=0.5,
        alignment_translation_coarse_step_m=0.25,
        alignment_translation_fine_step_m=0.05,
        alignment_yaw_search_radians=math.radians(4),
        alignment_yaw_coarse_step_radians=math.radians(2),
        alignment_yaw_fine_step_radians=math.radians(1),
        alignment_min_overlap=0.7,
        alignment_min_coverage=0.7,
        robot_clearance_m=0.1,
        route_candidate_count=3,
        route_distinctness_min=0.1,
        safe_zone_count=2,
        safe_zone_min_clearance_m=0.5,
        safe_zone_spacing_m=1.0,
        safe_zone_change_distance_m=0.5,
    )
    pipeline = AnalysisPipeline(
        slam=slam,
        risk=RuleBasedRiskAssessmentProvider(minimum_passage_width_m=0.5),
        route=AStarRoutePlanner(),
        teams=RuleBasedTeamRecommendationProvider(),
        mission_transform=ProvisionalMissionTransform(
            mode="configured", translation_x_m=0.0, translation_y_m=0.0, yaw_radians=0.0
        ),
        stage4=Stage4Processor(stage4_config, occupied_threshold=65, minimum_passage_width_m=0.5),
    )
    candidate = PersonCandidate(
        detection_id="victim-1",
        tracking_id="track-1",
        class_name="person",
        bbox=BoundingBox(1, 1, 10, 10),
        confidence=0.9,
        depth_valid=True,
        camera_position=CameraPoint(0.0, 0.0, 2.0),
        map_position=Point2D(9.25, 5.25),
        detected_at=STAMP,
        source="stage4_replay",
        observation_count=2,
    )
    service = Stage4JetsonApiService(
        manager,
        pipeline=pipeline,
        candidate_source=lambda: (candidate,),
        mode="real",
        analysis_readiness=lambda: None,
        stage4_config=stage4_config,
    )
    response = service.analyze()
    result = response["result"]
    assert result["coordinate_frame"] == "mission_map"
    assert result["map_alignment"]["status"] == "aligned"
    assert result["map_alignment"]["automatic_map_alignment"] is True
    assert response["map_preview"]["frame_id"] == "mission_map"
    assert response["map_preview"]["coordinate_frame"] == "mission_map"
    assert len(result["entry_routes"]) >= 1
    assert all(item["target_id"] == "victim-1" for item in result["entry_routes"])
    assert (applied.directory / "alignment.json").is_file()
    assert (applied.directory / "change_map.json").is_file()
    assert (applied.directory / "traversability.json").is_file()

    artifacts = current_analysis_artifacts(manager)
    assert artifacts.semantic_result_path.is_file()
    assert artifacts.map_preview_path.is_file()
    metadata = read_map_preview_metadata(artifacts.map_preview_path)
    assert metadata.mission_id == "stage4-service"
    assert metadata.base_map_version == 1
    assert metadata.artifact_version == 1
    assert metadata.resolution_m_per_cell == pytest.approx(mpp)
