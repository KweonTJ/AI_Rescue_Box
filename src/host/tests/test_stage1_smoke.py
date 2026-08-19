import importlib.util

import pytest

from host_app.map_editor import CoordinateTransform, Point
from host_app.mission.review import ReviewSession


def _semantic_result() -> dict:
    return {
        "schema_version": "1.0",
        "mission_id": "mission-smoke",
        "base_map_version": 1,
        "slam_map_version": 1,
        "result_version": 1,
        "artifact_version": 1,
        "created_at": "2026-08-19T00:00:00Z",
        "coordinate_frame": "mission_map",
        "units": "meters",
        "source": "jetson_sensor_analysis",
        "confidence": 0.8,
        "analysis_mode": "mock",
        "robot_pose": {"x": 0.0, "y": 0.0, "yaw": 0.0},
        "robot_trajectory": [],
        "victim_candidates": [],
        "confirmed_victims": [],
        "obstacles": [],
        "risk_zones": [],
        "entry_routes": [],
        "team_recommendations": [],
        "safe_waiting_points": [],
        "explored_areas": [],
        "unknown_areas": [],
    }


def test_coordinate_transform_round_trip_uses_mission_map() -> None:
    transform = CoordinateTransform(
        Point(10, 20),
        0.2,
        rotation_radians=0.3,
        invert_y=True,
    )
    source = Point(15, 27)
    restored = transform.map_to_image(transform.image_to_map(source))
    assert transform.frame_id == "mission_map"
    assert restored.x == pytest.approx(source.x)
    assert restored.y == pytest.approx(source.y)


def test_review_builds_basic_approved_plan() -> None:
    review = ReviewSession(_semantic_result())
    review.set_notes("stage1 smoke")
    plan = review.build_approved_plan(1).to_dict()
    assert plan["mission_id"] == "mission-smoke"
    assert plan["base_result_version"] == 1
    assert plan["approved_plan_version"] == 1
    assert plan["coordinate_frame"] == "mission_map"
    assert plan["notes"] == "stage1 smoke"


def test_host_api_health_route_without_runtime_transport() -> None:
    if importlib.util.find_spec("fastapi") is None:
        pytest.skip("fastapi not installed")

    from fastapi.testclient import TestClient
    from host_app.api import create_app

    class HealthOnlyService:
        def health(self) -> dict:
            return {
                "ok": True,
                "service": "ai-rescue-box-host-api",
                "schema_version": "1.0",
                "bridge_state": "mock",
            }

    with TestClient(create_app(service=HealthOnlyService())) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["service"] == "ai-rescue-box-host-api"
