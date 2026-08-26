from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

from PIL import Image

from host_app.api.service import HostApiService
from host_app.mission.models import SemanticResult


def _mission_and_map() -> tuple[dict, bytes]:
    output = BytesIO()
    Image.new("RGB", (12, 8), "white").save(output, format="PNG")
    base_map = output.getvalue()
    return (
        {
            "schema_version": "1.0",
            "mission_id": "final-map-test",
            "mission_version": 1,
            "artifact_version": 1,
            "mission_name": "Final Map Test",
            "created_at": "2026-08-26T00:00:00Z",
            "base_map": {
                "filename": "base_map.png",
                "sha256": hashlib.sha256(base_map).hexdigest(),
                "width": 12,
                "height": 8,
            },
            "meters_per_pixel": 0.1,
            "robot_start": {"x": 1.0, "y": 1.0, "yaw": 0.0},
            "entrances": [{"x": 0.0, "y": 0.0}],
            "available_teams": 1,
            "available_rescuers": 2,
            "coordinate_frame": "mission_map",
            "units": "meters",
            "source": "tablet",
            "confidence": 1.0,
        },
        base_map,
    )


def _semantic() -> dict:
    return {
        "schema_version": "1.0",
        "mission_id": "final-map-test",
        "base_map_version": 1,
        "slam_map_version": 1,
        "result_version": 1,
        "artifact_version": 1,
        "created_at": "2026-08-26T00:01:00Z",
        "coordinate_frame": "mission_map",
        "units": "meters",
        "source": "jetson_sensor_analysis",
        "confidence": 0.9,
        "robot_pose": {"x": 1.0, "y": 1.0, "yaw": 0.0},
        "robot_trajectory": [],
        "victim_candidates": [],
        "confirmed_victims": [],
        "obstacles": [],
        "risk_zones": [],
        "entry_routes": [
            {
                "route_id": "entry-route-1",
                "target_id": "victim-1",
                "points": [
                    {"x": 0.0, "y": 0.0},
                    {"x": 1.0, "y": 1.0},
                ],
            }
        ],
        "team_recommendations": [],
        "safe_waiting_points": [],
        "explored_areas": [],
        "unknown_areas": [],
    }


def test_final_map_requires_publish_and_never_starts_uwb_operation(
    tmp_path: Path,
) -> None:
    service = HostApiService(tmp_path / "host")
    manifest, base_map = _mission_and_map()
    try:
        service.sync_jetson_mission(manifest, base_map)
        service.store.save_semantic_result(SemanticResult(_semantic()), 1)
        service.load_result("final-map-test", 1, 1)

        reviewed = service.apply_review_command(
            "final-map-test",
            1,
            1,
            "set_route_approved",
            {"route_id": "entry-route-1", "approved": True},
            0,
        )
        assert reviewed["host_edits"]["route_approvals"] == {
            "entry-route-1": True
        }
        assert reviewed["reviewed_result"]["entry_routes"][0][
            "host_status"
        ] == "approved"

        assert service.current_final_map_state() == {
            "state": "waiting",
            "reason": "final_map_not_published",
        }

        published = service.publish_final_map()
        assert published["state"] == "ready"
        assert published["result_version"] == 1
        assert published["approved_plan_version"] == 1
        assert published["approved_plan"]["approved_plan_version"] == 1
        assert published["approved_plan"]["approved_routes"] == [
            {
                "route_id": "entry-route-1",
                "target_id": "victim-1",
                "points": [
                    {"x": 0.0, "y": 0.0},
                    {"x": 1.0, "y": 1.0},
                ],
                "host_status": "approved",
            }
        ]
        assert published["base_map_url"] == (
            "/api/v1/missions/final-map-test/1/base-map"
        )
        assert (tmp_path / "host" / "published_final_map.json").is_file()
        assert service.current_final_map_state() == published

        republished_without_edits = service.publish_final_map()
        assert republished_without_edits["approved_plan_version"] == 2
        assert republished_without_edits["approved_plan"]["approved_routes"] == (
            published["approved_plan"]["approved_routes"]
        )
        assert service.current_final_map_state() == republished_without_edits

        service.apply_review_command(
            "final-map-test",
            1,
            1,
            "set_notes",
            {"notes": "updated"},
            1,
        )
        republished = service.publish_final_map()
        assert republished["approved_plan_version"] == 3
        assert republished["approved_plan"]["notes"] == "updated"
        assert republished["approved_plan"]["approved_routes"] == (
            published["approved_plan"]["approved_routes"]
        )
        assert service.current_final_map_state() == republished
        assert service.status()["operations"] == {}
    finally:
        service.close()


def test_final_map_rebuilds_approved_plan_from_current_review(
    tmp_path: Path,
) -> None:
    service = HostApiService(tmp_path / "host")
    manifest, base_map = _mission_and_map()
    try:
        service.sync_jetson_mission(manifest, base_map)
        service.store.save_semantic_result(SemanticResult(_semantic()), 1)
        service.load_result("final-map-test", 1, 1)

        cached = service.build_approved_plan("final-map-test", 1, 1, 1)
        assert cached["approved_routes"] == []

        reviewed = service.apply_review_command(
            "final-map-test",
            1,
            1,
            "set_route_approved",
            {"route_id": "entry-route-1", "approved": True},
            0,
        )
        assert reviewed["host_edits"]["route_approvals"] == {
            "entry-route-1": True
        }

        published = service.publish_final_map()
        assert published["approved_plan_version"] == 2
        assert published["approved_plan"]["approved_routes"] == [
            {
                "route_id": "entry-route-1",
                "target_id": "victim-1",
                "points": [
                    {"x": 0.0, "y": 0.0},
                    {"x": 1.0, "y": 1.0},
                ],
                "host_status": "approved",
            }
        ]
        assert service.current_final_map_state()["approved_plan"] == (
            published["approved_plan"]
        )
    finally:
        service.close()
