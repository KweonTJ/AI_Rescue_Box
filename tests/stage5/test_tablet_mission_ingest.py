from __future__ import annotations

import io
import math
from pathlib import Path

import pytest
from PIL import Image

from jetson_app.mission.manager import MissionManager
from jetson_app.mission.preprocess import FloorplanProcessingResult
from jetson_app.mission.tablet_ingest import TabletMissionIngestor


def _png() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (32, 24), "white").save(output, format="PNG")
    return output.getvalue()


class _FakePreprocessor:
    def process(self, source: Path) -> FloorplanProcessingResult:
        content = _png()
        return FloorplanProcessingResult(
            display_png=content,
            wall_mask_png=content,
            metadata={"pipeline": "fake_test_pipeline"},
        )


def _draft(**extra):
    value = {
        "mission_name": "Tablet Mission",
        "meters_per_pixel": 0.1,
        "robot_start_image": {"x": 100.0, "y": 100.0},
        "initial_yaw": math.pi / 2,
        "entrances": [{"x": 100.0, "y": 80.0}],
        "available_teams": 1,
        "available_rescuers": 2,
        "notes": "tablet test",
    }
    value.update(extra)
    return value


def test_tablet_ingest_stores_v1_without_activating(tmp_path: Path) -> None:
    manager = MissionManager(tmp_path / "missions")
    ingest = TabletMissionIngestor(manager, preprocessor=_FakePreprocessor())

    stored = ingest.store(
        _draft(mission_id="tablet-a"),
        base_map_filename="floor.png",
        base_map_bytes=_png(),
    )

    assert stored.manifest.mission_id == "tablet-a"
    assert stored.manifest.mission_version == 1
    assert stored.manifest.source == "tablet"
    assert stored.manifest.robot_start.x == pytest.approx(0.0)
    assert stored.manifest.robot_start.y == pytest.approx(0.0)
    assert stored.manifest.robot_start.yaw == pytest.approx(0.0)
    assert stored.manifest.entrances[0].x == pytest.approx(-2.0)
    assert stored.manifest.entrances[0].y == pytest.approx(0.0, abs=1e-9)
    assert manager.current_mission_ref() is None

    for name in (
        "base_map.png",
        "base_map_original.png",
        "base_map_display.png",
        "wall_mask.png",
        "mission_manifest.json",
        "processing.json",
        "verification.json",
    ):
        assert (stored.directory / name).is_file(), name


def test_tablet_edit_reuses_map_and_creates_next_version(tmp_path: Path) -> None:
    manager = MissionManager(tmp_path / "missions")
    ingest = TabletMissionIngestor(manager, preprocessor=_FakePreprocessor())
    first = ingest.store(
        _draft(mission_id="tablet-a"),
        base_map_filename="floor.png",
        base_map_bytes=_png(),
    )

    second = ingest.store(
        _draft(mission_id="tablet-a", mission_name="Tablet Mission revised"),
        reuse_from_version=1,
    )

    assert first.manifest.mission_version == 1
    assert second.manifest.mission_version == 2
    assert second.manifest.mission_name == "Tablet Mission revised"
    assert second.manifest.extra["reused_base_map_from_version"] == 1
    assert (second.directory / "base_map_display.png").read_bytes() == (
        first.directory / "base_map_display.png"
    ).read_bytes()
    assert manager.current_mission_ref() is None


def test_tablet_edit_cannot_skip_versions(tmp_path: Path) -> None:
    manager = MissionManager(tmp_path / "missions")
    ingest = TabletMissionIngestor(manager, preprocessor=_FakePreprocessor())
    ingest.store(
        _draft(mission_id="tablet-a"),
        base_map_filename="floor.png",
        base_map_bytes=_png(),
    )

    with pytest.raises(ValueError, match="must be v2"):
        ingest.store(
            _draft(mission_id="tablet-a", mission_version=4),
            reuse_from_version=1,
        )
