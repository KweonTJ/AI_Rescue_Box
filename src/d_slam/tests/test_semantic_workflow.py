from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

from jetson_app.ai_boost import ai_boost
from jetson_app.api.continuous_service import ContinuousStage4JetsonApiService
from jetson_app.mission import MissionManager
from jetson_app.mission.application import MissionApplicationService
from jetson_app.semantic_updates import SemanticChangeDetector

STAMP = "2026-08-20T00:00:00Z"


def _write_mission(tmp_path: Path, mission_id: str, version: int):
    image_path = tmp_path / f"{mission_id}-v{version}.png"
    Image.new("RGB", (12, 10), "white").save(image_path)
    digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
    manifest = {
        "schema_version": "1.0",
        "mission_id": mission_id,
        "mission_version": version,
        "artifact_version": version,
        "mission_name": f"Mission {mission_id} v{version}",
        "created_at": STAMP,
        "base_map_filename": image_path.name,
        "base_map_sha256": digest,
        "base_map_width": 12,
        "base_map_height": 10,
        "meters_per_pixel": 0.1,
        "robot_start": {"x": 0.5, "y": 0.5, "yaw": 0.0},
        "entrances": [{"x": 0.5, "y": 0.5}],
        "available_teams": 1,
        "available_rescuers": 2,
        "coordinate_frame": "mission_map",
        "units": "meters",
        "source": "host",
        "confidence": 1.0,
    }
    manifest_path = tmp_path / f"{mission_id}-v{version}.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path, image_path


def _semantic(version: int, *, victim: bool = False, critical: bool = False, route: bool = True):
    victims = []
    if victim:
        victims.append({
            "detection_id": "victim-1",
            "confidence": 0.95,
            "map_position": {"x": 2.0, "y": 3.0},
            "source": "test",
        })
    risks = []
    if critical:
        risks.append({"risk_id": "risk-1", "severity": 0.9, "risk_type": "collapse"})
    routes = []
    if route:
        routes.append({"route_id": "route-1", "points": [{"x": 0.5, "y": 0.5}, {"x": 2, "y": 3}]})
    return {
        "schema_version": "1.0",
        "mission_id": "mission-A",
        "base_map_version": 1,
        "slam_map_version": version,
        "result_version": version,
        "artifact_version": version,
        "created_at": f"2026-08-20T00:00:0{min(version,9)}Z",
        "coordinate_frame": "mission_map",
        "units": "meters",
        "source": "jetson_mock_analysis",
        "confidence": 0.9,
        "analysis_mode": "mock",
        "robot_pose": {"x": 0.5, "y": 0.5, "yaw": 0.0},
        "robot_trajectory": [],
        "victim_candidates": victims,
        "confirmed_victims": [],
        "obstacles": [],
        "risk_zones": risks,
        "entry_routes": routes,
        "team_recommendations": [],
        "safe_waiting_points": [],
        "explored_areas": [],
        "unknown_areas": [],
        "map_alignment": {"status": "provisional", "provenance": "observed"},
    }


class _Result:
    def __init__(self, value): self._value = value
    def to_dict(self): return dict(self._value)


class _Report:
    def __init__(self, value):
        self.result = _Result(value)
        self.stage4_artifacts = None


class _Pipeline:
    def __init__(self): self.calls = 0
    def run(self, *, result_version, **kwargs):
        del kwargs
        self.calls += 1
        # First and second iterations are semantically identical. The third adds a victim.
        return _Report(_semantic(result_version, victim=self.calls >= 3))


class _Transport:
    def __init__(self): self.items = []
    def status(self): return {"connected": True}
    def _send(self, kind, payload, path, priority):
        self.items.append((kind, dict(payload), Path(path), priority))
        return {"success": True, "state": "queued", "application_ack": False}
    def send_semantic_result(self, payload, path, *, priority=0): return self._send("semantic_result", payload, path, priority)
    def send_map_delta(self, payload, path, *, priority=0): return self._send("map_delta", payload, path, priority)
    def send_urgent_event(self, payload, path, *, priority=0): return self._send("urgent_event", payload, path, priority)
    def send_map_preview(self, payload, path, *, priority=0): return self._send("map_preview", payload, path, priority)


def test_d_slam_ai_boost_disabled_preserves_deterministic_behavior():
    marker = object()
    assert ai_boost("alignment", lambda: marker, enabled=False) is marker


def test_mission_receive_stores_without_changing_active_until_selection(tmp_path: Path):
    manager = MissionManager(tmp_path / "missions")
    v1_manifest, v1_map = _write_mission(tmp_path, "mission-A", 1)
    manager.apply_mission(v1_manifest, v1_map)
    assert manager.current_mission_ref() is None
    manager.set_current_mission("mission-A", 1)
    assert manager.current_mission_ref() == ("mission-A", 1)

    v2_manifest, v2_map = _write_mission(tmp_path, "mission-A", 2)
    application = MissionApplicationService(manager)
    stored = application.load_mission(
        mission_id="mission-A",
        mission_version=2,
        base_map_path=v2_map,
        mission_manifest_path=v2_manifest,
    )
    assert stored.success is True
    assert stored.state == "STORED"
    assert "selection is required" in stored.message.lower()
    assert manager.current_mission_ref() == ("mission-A", 1)

    duplicate = application.load_mission(
        mission_id="mission-A",
        mission_version=2,
        base_map_path=v2_map,
        mission_manifest_path=v2_manifest,
    )
    assert duplicate.success is True
    assert duplicate.state == "STORED"
    assert manager.current_mission_ref() == ("mission-A", 1)

    resets = []
    service = ContinuousStage4JetsonApiService(
        manager,
        pipeline=_Pipeline(),
        candidate_source=lambda: (),
        transport=_Transport(),
        mode="mock",
        mission_reset=lambda: resets.append("reset"),
        semantic_poll_seconds=60,
    )
    service.select_mission("mission-A", 2)
    assert manager.current_mission_ref() == ("mission-A", 2)
    assert resets == ["reset"]


def test_semantic_change_detector_suppresses_timestamp_only_and_deduplicates_urgent_events():
    detector = SemanticChangeDetector()
    assert detector.observe(_semantic(1)).changed is True
    same = _semantic(2)
    same["created_at"] = "2026-08-20T01:23:45Z"
    assert detector.observe(same).changed is False

    victim = _semantic(2, victim=True)
    update = detector.observe(victim)
    assert update.changed is True
    assert update.delta["base_result_version"] == 1
    assert update.delta["result_version"] == 2
    assert [event["event_type"] for event in update.urgent_events] == ["new_victim"]

    # A changed non-victim field must not repeat the unchanged victim alert.
    risk = _semantic(3, victim=True, critical=True)
    update2 = detector.observe(risk)
    assert "critical_risk" in [event["event_type"] for event in update2.urgent_events]
    assert "new_victim" not in [event["event_type"] for event in update2.urgent_events]

    blocked = _semantic(4, victim=True, critical=True, route=False)
    update3 = detector.observe(blocked)
    assert "route_blocked" in [event["event_type"] for event in update3.urgent_events]


def test_continuous_monitor_requires_selection_then_sends_initial_delta_and_urgent(tmp_path: Path):
    manager = MissionManager(tmp_path / "missions")
    manifest, base_map = _write_mission(tmp_path, "mission-A", 1)
    manager.apply_mission(manifest, base_map)
    pipeline = _Pipeline()
    transport = _Transport()
    service = ContinuousStage4JetsonApiService(
        manager,
        pipeline=pipeline,
        candidate_source=lambda: (),
        transport=transport,
        mode="mock",
        semantic_poll_seconds=60,
    )

    assert service.semantic_update_tick()["state"] == "inactive"
    assert pipeline.calls == 0
    assert transport.items == []

    service.select_mission("mission-A", 1)
    first = service.semantic_update_tick()
    assert first["artifact_type"] == "semantic_result"
    assert [item[0] for item in transport.items] == ["semantic_result"]
    assert manager.latest_result_version("mission-A", 1) == 1

    second = service.semantic_update_tick()
    assert second["state"] == "no_change"
    assert [item[0] for item in transport.items] == ["semantic_result"]
    assert manager.latest_result_version("mission-A", 1) == 1

    third = service.semantic_update_tick()
    assert third["artifact_type"] == "map_delta"
    assert [item[0] for item in transport.items][-2:] == ["map_delta", "urgent_event"]
    assert transport.items[-1][1]["event_type"] == "new_victim"
    assert manager.latest_result_version("mission-A", 1) == 2
