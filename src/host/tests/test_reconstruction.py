from __future__ import annotations

import threading

import pytest

from host_app.ai_boost import ai_boost
import host_app.reconstruction as reconstruction_module
from host_app.mission.models import SemanticResult
from host_app.mission.review import ReviewSession
from host_app.mission.workflow import ReceivedArtifactLoader
from host_app.reconstruction import HostSemanticReconstructor, VersionGapError

STAMP = "2026-08-20T00:00:00Z"


def _semantic(version: int, *, x: float = 0.0):
    return {
        "schema_version": "1.0",
        "mission_id": "mission-A",
        "base_map_version": 1,
        "slam_map_version": version,
        "result_version": version,
        "artifact_version": version,
        "created_at": STAMP,
        "coordinate_frame": "mission_map",
        "units": "meters",
        "source": "jetson_sensor_analysis",
        "confidence": 0.9,
        "analysis_mode": "real",
        "robot_pose": {"x": x, "y": 0.0, "yaw": 0.0},
        "robot_trajectory": [],
        "victim_candidates": [{
            "detection_id": "victim-1",
            "confidence": 0.9,
            "map_position": {"x": 2.0, "y": 3.0},
        }],
        "confirmed_victims": [],
        "obstacles": [],
        "risk_zones": [],
        "entry_routes": [{"route_id": "route-1", "points": []}],
        "team_recommendations": [],
        "safe_waiting_points": [],
        "explored_areas": [],
        "unknown_areas": [],
    }


def _delta(base: int, result: int, *, x: float):
    return {
        "schema_version": "1.0",
        "mission_id": "mission-A",
        "artifact_version": result,
        "base_result_version": base,
        "result_version": result,
        "base_map_version": 1,
        "slam_map_version": result,
        "analysis_mode": "real",
        "created_at": STAMP,
        "coordinate_frame": "mission_map",
        "source": "jetson_semantic_change_monitor",
        "confidence": 0.9,
        "changed_regions": [],
        "semantic_updates": {"robot_pose": {"x": x, "y": 0.0, "yaw": 0.0}},
    }


def test_host_ai_boost_disabled_reconstructs_deterministically():
    result = ai_boost(_semantic(1), _delta(1, 2, x=2.0), enabled=False)
    assert result["result_version"] == 2
    assert result["robot_pose"]["x"] == 2.0
    assert result["source"] == "host_reconstructed_semantic_delta"


def test_reconstruction_runtime_passes_delta_through_host_ai_boost(monkeypatch):
    calls = []
    real = reconstruction_module.ai_boost

    def recording(previous, delta, **kwargs):
        calls.append((previous["result_version"], delta["result_version"]))
        return real(previous, delta, **kwargs)

    monkeypatch.setattr(reconstruction_module, "ai_boost", recording)
    reconstructor = HostSemanticReconstructor()
    reconstructor.apply_semantic_result(_semantic(1))
    reconstructor.apply_delta(_delta(1, 2, x=2.0))
    assert calls == [(1, 2)]


def test_host_reconstructs_v1_v2_v3_and_protects_stale_duplicate_and_gap():
    reconstructor = HostSemanticReconstructor()
    initial = reconstructor.apply_semantic_result(_semantic(1))
    assert initial.applied is True
    assert initial.state["result_version"] == 1

    v2_delta = _delta(1, 2, x=2.0)
    v2 = reconstructor.apply_delta(v2_delta)
    assert v2.applied is True
    assert v2.state["result_version"] == 2
    assert v2.state["robot_pose"]["x"] == 2.0

    duplicate = reconstructor.apply_delta(v2_delta)
    assert duplicate.applied is False
    assert duplicate.duplicate is True
    assert duplicate.state["result_version"] == 2

    v3 = reconstructor.apply_delta(_delta(2, 3, x=3.0))
    assert v3.applied is True
    assert v3.state["result_version"] == 3
    assert v3.state["robot_pose"]["x"] == 3.0

    stale = reconstructor.apply_delta(_delta(1, 2, x=99.0))
    assert stale.applied is False
    assert stale.stale is True
    assert stale.state["robot_pose"]["x"] == 3.0

    with pytest.raises(VersionGapError):
        reconstructor.apply_delta(_delta(4, 5, x=5.0))


def test_review_overlay_is_rebased_to_new_source_state_instead_of_silently_lost():
    class Events:
        def __init__(self): self.items = []
        def publish(self, kind, payload): self.items.append((kind, payload))

    class Owner:
        def __init__(self):
            self._lock = threading.RLock()
            self._reviews = {}
            self._review_revisions = {}
            self.events = Events()
        def receive(self, semantic, notice):
            del notice
            key = (semantic.mission_id, 1, semantic.result_version)
            self._reviews[key] = ReviewSession(semantic)
            self._review_revisions[key] = 0
            return True

    class Bridge:
        def add_received_listener(self, callback): self.callback = callback
        def remove_received_listener(self, callback): pass

    owner = Owner()
    first = SemanticResult(_semantic(1))
    owner.receive(first, None)
    previous = owner._reviews[("mission-A", 1, 1)]
    previous.set_victim_priority("victim-1", 1)
    previous.set_notes("operator note")
    owner._review_revisions[("mission-A", 1, 1)] = 2

    loader = ReceivedArtifactLoader(Bridge(), on_semantic_result=owner.receive)
    second = SemanticResult(_semantic(2, x=2.0))
    owner.receive(second, None)
    loader._preserve_review_overlay(second)
    rebased = owner._reviews[("mission-A", 1, 2)]
    assert rebased.host_edits["victim_priorities"] == {"victim-1": 1}
    assert rebased.host_edits["notes"] == "operator note"
    assert owner._review_revisions[("mission-A", 1, 2)] == 3
    assert any(kind == "review.rebased" for kind, _ in owner.events.items)
