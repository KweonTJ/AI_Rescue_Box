from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from host_app.map_editor import read_map_preview_metadata
from jetson_app.alignment import ProvisionalMissionTransform
from jetson_app.analysis import AnalysisPipeline
from jetson_app.api import create_app
from jetson_app.api.service import JetsonApiService
from jetson_app.domain import BoundingBox, OccupancyGrid, Point2D, Pose2D
from jetson_app.map_preview import OccupancyPreviewRenderer
from jetson_app.mission import MissionManager
from jetson_app.perception import PersonFusionEngine
from jetson_app.planning import AStarRoutePlanner, RuleBasedTeamRecommendationProvider
from jetson_app.providers.base import (
    CameraIntrinsics,
    Detection2D,
    PersonDetectionProvider,
    ProviderMode,
    ProviderStatus,
    RgbFrame,
)
from jetson_app.risk import RuleBasedRiskAssessmentProvider
from jetson_app.ros_client.adapters import (
    AstraDepthProvider,
    RosDependencyState,
    RosMapTransformer,
    RtabmapSlamProvider,
)
from jetson_app.stage2_submit import current_analysis_artifacts


STAMP = "2026-08-20T00:00:00Z"


class StaticRealDetector(PersonDetectionProvider):
    def status(self) -> ProviderStatus:
        return ProviderStatus("replay person detector", ProviderMode.REAL, True, "ready")

    def detect(self, frame: RgbFrame):
        return (
            Detection2D(
                bbox=BoundingBox(50, 40, 20, 20),
                confidence=0.9,
                tracking_id="track-1",
                detection_id="person-1",
                timestamp=frame.timestamp,
            ),
        )


def _mission(manager: MissionManager, tmp_path: Path):
    image_path = tmp_path / "prior.png"
    Image.new("RGB", (80, 80), "white").save(image_path)
    digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
    manifest = {
        "schema_version": "1.0",
        "mission_id": "stage3-mission",
        "mission_version": 1,
        "artifact_version": 1,
        "mission_name": "Stage 3 deterministic replay",
        "created_at": STAMP,
        "base_map_filename": "prior.png",
        "base_map_sha256": digest,
        "base_map_width": 80,
        "base_map_height": 80,
        "meters_per_pixel": 0.1,
        "robot_start": {"x": 10.5, "y": 20.5, "yaw": 0.0},
        "entrances": [{"x": 10.5, "y": 20.5}],
        "available_teams": 1,
        "available_rescuers": 2,
        "coordinate_frame": "mission_map",
        "units": "meters",
        "source": "host",
        "confidence": 1.0,
    }
    manifest_path = tmp_path / "mission_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manager.apply_mission(manifest_path, image_path)


def _real_dependencies() -> RosDependencyState:
    return RosDependencyState(True, True, True, True, True, True, True)


def test_real_replay_fuses_depth_tf_plans_and_stores_stage2_compatible_result(tmp_path: Path):
    manager = MissionManager(tmp_path / "missions")
    mission = _mission(manager, tmp_path)

    values = [0] * 64
    values[6 * 8 + 6] = 100
    grid = OccupancyGrid(8, 8, 1.0, Point2D(0.0, 0.0), tuple(values), frame_id="map")
    slam = RtabmapSlamProvider(_real_dependencies())
    slam.update(
        occupancy_grid=grid,
        robot_pose=Pose2D(1.5, 1.5, 0.0),
        trajectory=(Pose2D(1.5, 1.5, 0.0),),
        explored_areas=((Point2D(0, 0), Point2D(8, 0), Point2D(8, 8), Point2D(0, 8)),),
        unknown_areas=(),
        tracking_status="tracking",
        map_version=3,
    )

    depth = AstraDepthProvider(
        dependency_state=_real_dependencies(),
        minimum_depth_m=0.15,
        maximum_depth_m=10.0,
        maximum_sync_age_s=0.25,
    )
    depth.update_depth(
        [[2000] * 100 for _ in range(100)],
        CameraIntrinsics(100, 100, 100.0, 100.0, 50.0, 50.0, "camera_depth_optical_frame"),
        depth_scale=0.001,
        timestamp=STAMP,
    )
    transformer = RosMapTransformer(
        lambda point, source, target, timestamp: Point2D(point.x + 2.0, point.z + 1.0),
        target_frame="map",
    )
    fusion = PersonFusionEngine(StaticRealDetector(), depth, transformer)
    frame = RgbFrame(100, 100, b"replay", "rgb8", "camera_color_optical_frame", STAMP)
    first = fusion.process(frame)
    assert first[0].camera_position is not None
    assert first[0].camera_position.x == pytest.approx(0.2)
    assert first[0].camera_position.z == pytest.approx(2.0)
    assert first[0].map_position == Point2D(2.2, 3.0)
    assert first[0].observation_count == 1
    candidates = fusion.process(frame)
    assert candidates[0].observation_count == 2

    transform = ProvisionalMissionTransform(mode="initial_anchor")
    pipeline = AnalysisPipeline(
        slam=slam,
        risk=RuleBasedRiskAssessmentProvider(),
        route=AStarRoutePlanner(),
        teams=RuleBasedTeamRecommendationProvider(),
        mission_transform=transform,
        confirmation_observations=2,
    )
    service = JetsonApiService(
        manager,
        pipeline=pipeline,
        preview_renderer=OccupancyPreviewRenderer(max_dimension=64),
        candidate_source=lambda: candidates,
        mode="real",
        analysis_readiness=lambda: None,
        map_alignment_source=lambda manifest: transform.resolve(
            manifest, slam.snapshot().robot_pose
        ).metadata(),
    )

    response = service.analyze()
    result = response["result"]
    assert result["analysis_mode"] == "real"
    assert result["coordinate_frame"] == "mission_map"
    assert result["victim_candidates"][0]["map_position"]["x"] == pytest.approx(11.2)
    assert result["victim_candidates"][0]["map_position"]["y"] == pytest.approx(22.0)
    assert len(result["confirmed_victims"]) == 1
    assert result["entry_routes"]
    assert any(zone["risk_type"] == "obstacle_candidate" for zone in result["risk_zones"])
    assert result["map_alignment"]["mode"] == "initial_anchor"
    assert result["map_alignment"]["status"] == "provisional"
    assert result["map_alignment"]["automatic_map_alignment"] is False

    stored = manager.load_semantic_result("stage3-mission", 1, 1)
    assert stored["analysis_mode"] == "real"
    assert response["map_preview"]["frame_id"] == "map"
    assert response["map_preview"]["coordinate_frame"] == "mission_map"
    artifacts = current_analysis_artifacts(manager)
    assert artifacts.semantic_result_path.is_file()
    assert artifacts.map_preview_path.is_file()
    assert artifacts.result_version == 1
    host_preview = read_map_preview_metadata(artifacts.map_preview_path)
    assert host_preview.mission_id == "stage3-mission"
    assert host_preview.base_map_version == 1
    assert host_preview.artifact_version == 1
    assert host_preview.resolution_m_per_cell == pytest.approx(1.0)


def test_real_analysis_unavailable_never_falls_back_to_mock(tmp_path: Path):
    manager = MissionManager(tmp_path / "missions")
    _mission(manager, tmp_path)
    slam = RtabmapSlamProvider(_real_dependencies())
    slam.update(
        occupancy_grid=OccupancyGrid(2, 2, 1.0, Point2D(0, 0), (0, 0, 0, 0), frame_id="map"),
        robot_pose=Pose2D(0.5, 0.5),
        trajectory=(),
        explored_areas=(),
        unknown_areas=(),
        tracking_status="tracking",
        map_version=1,
    )
    pipeline = AnalysisPipeline(
        slam=slam,
        risk=RuleBasedRiskAssessmentProvider(),
        route=AStarRoutePlanner(),
        teams=RuleBasedTeamRecommendationProvider(),
    )
    service = JetsonApiService(
        manager,
        pipeline=pipeline,
        candidate_source=lambda: (),
        mode="real",
        analysis_readiness=lambda: (_ for _ in ()).throw(
            RuntimeError("MODEL_NOT_CONFIGURED: model_path is not configured")
        ),
    )
    from fastapi.testclient import TestClient

    response = TestClient(create_app(service)).post("/api/v1/analysis")
    assert response.status_code == 503
    assert "MODEL_NOT_CONFIGURED" in response.json()["detail"]
    assert manager.latest_result_version("stage3-mission", 1) is None
