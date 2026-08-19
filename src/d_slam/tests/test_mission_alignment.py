import hashlib
import json
from pathlib import Path

from PIL import Image

from jetson_app.alignment import PriorSlamAlignmentEvaluator
from jetson_app.domain import MissionManifest, OccupancyGrid, Point2D, Pose2D
from jetson_app.mission import MissionManager
from jetson_app.providers.base import SlamSnapshot


def _manifest(sha256: str) -> dict:
    return {
        "schema_version": "1.0",
        "mission_id": "mission-smoke",
        "mission_version": 1,
        "artifact_version": 1,
        "mission_name": "Stage 1 smoke",
        "created_at": "2026-08-19T00:00:00Z",
        "base_map_filename": "map.png",
        "base_map_sha256": sha256,
        "base_map_width": 4,
        "base_map_height": 3,
        "meters_per_pixel": 0.5,
        "robot_start": {"x": 0.0, "y": 0.0, "yaw": 0.0},
        "entrances": [{"x": 0.0, "y": 0.0}],
        "available_teams": 1,
        "available_rescuers": 2,
        "coordinate_frame": "mission_map",
        "units": "meters",
        "source": "host",
        "confidence": 1.0,
    }


def test_mission_manager_stores_and_loads_verified_mission(tmp_path: Path) -> None:
    base_map = tmp_path / "map.png"
    Image.new("RGB", (4, 3), "white").save(base_map)
    digest = hashlib.sha256(base_map.read_bytes()).hexdigest()
    manifest_path = tmp_path / "mission_manifest.json"
    manifest_path.write_text(json.dumps(_manifest(digest)), encoding="utf-8")

    manager = MissionManager(tmp_path / "missions")
    applied = manager.apply_mission(manifest_path, base_map)
    loaded = manager.load_mission("mission-smoke", 1)

    assert applied.manifest.mission_id == "mission-smoke"
    assert loaded.manifest.mission_version == 1
    assert loaded.base_map_path.read_bytes() == base_map.read_bytes()
    assert manager.list_missions() == (("mission-smoke", 1),)


def test_alignment_returns_conservative_result_without_live_evidence() -> None:
    mission = MissionManifest.from_dict(_manifest("0" * 64))
    snapshot = SlamSnapshot(
        OccupancyGrid(2, 2, 0.5, Point2D(0.0, 0.0), (-1, -1, -1, -1)),
        Pose2D(0.0, 0.0),
        (),
        (),
        (),
        "tracking",
        1,
    )
    result = PriorSlamAlignmentEvaluator().evaluate(mission, snapshot)
    assert result["status"] == "insufficient_evidence"
    assert result["automatic_warp_applied"] is False
    assert result["alignment_confirmed"] is False
