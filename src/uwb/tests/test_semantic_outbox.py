from __future__ import annotations

import json
from pathlib import Path

from runtime.ai_boost import ai_boost
from runtime.persistent_outbox import PersistentOutbox


class Sender:
    def __init__(self, *, fail_versions=()):
        self.fail_versions = set(fail_versions)
        self.calls = []

    def send_artifact(self, path, *, artifact_type, mission_id, artifact_version, priority=100):
        self.calls.append((artifact_type, mission_id, artifact_version, priority, Path(path).name))
        if artifact_version in self.fail_versions and artifact_type == "map_delta":
            raise RuntimeError(f"offline v{artifact_version}")
        return {
            "success": True,
            "state": "completed",
            "application_ack": True,
            "transfer_id": f"tx-{artifact_type}-{artifact_version}",
        }


def _write(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def _delta(path: Path, base: int, result: int) -> Path:
    return _write(path, {
        "schema_version": "1.0",
        "mission_id": "mission-A",
        "artifact_version": result,
        "base_result_version": base,
        "result_version": result,
        "created_at": "2026-08-20T00:00:00Z",
        "coordinate_frame": "mission_map",
        "source": "test",
        "confidence": 1.0,
        "changed_regions": [],
        "semantic_updates": {"robot_pose": {"x": result, "y": 0, "yaw": 0}},
    })


def test_uwb_ai_boost_disabled_uses_deterministic_priority():
    urgent = ai_boost("urgent_event", {"event_type": "new_victim"}, enabled=False)
    delta = ai_boost("map_delta", {}, enabled=False)
    preview = ai_boost("map_preview", {}, enabled=False)
    assert urgent.priority == 255
    assert delta.priority >= 180
    assert preview.priority < delta.priority


def test_persistent_outbox_survives_disconnect_restart_and_deletes_only_after_ack(tmp_path: Path):
    source = _write(tmp_path / "semantic.json", {
        "mission_id": "mission-A", "artifact_version": 1, "result_version": 1
    })

    class Offline:
        def send_artifact(self, *args, **kwargs):
            raise RuntimeError("radio disconnected")

    root = tmp_path / "uwb_outbox"
    first = PersistentOutbox(root, Offline())
    queued = first.enqueue_and_try_send(
        source,
        artifact_type="semantic_result",
        mission_id="mission-A",
        artifact_version=1,
    )
    assert queued["success"] is True
    assert queued["state"] == "queued"
    assert queued["delivered"] is False
    assert len(first.entries()) == 1

    # Process restart: a new instance recovers metadata and payload from disk.
    sender = Sender()
    restarted = PersistentOutbox(root, sender)
    assert len(restarted.entries()) == 1
    outcomes = restarted.drain()
    assert outcomes[0]["success"] is True
    assert outcomes[0]["application_ack"] is True
    assert restarted.entries() == ()


def test_outbox_content_identity_is_idempotent_and_json_metadata_never_collides(tmp_path: Path):
    sender = Sender()
    root = tmp_path / "uwb_outbox"
    outbox = PersistentOutbox(root, sender)
    source = _write(tmp_path / "delta.json", {
        "mission_id": "mission-A",
        "artifact_version": 2,
        "base_result_version": 1,
        "result_version": 2,
    })
    first = outbox.enqueue(
        source, artifact_type="map_delta", mission_id="mission-A", artifact_version=2
    )
    second = outbox.enqueue(
        source, artifact_type="map_delta", mission_id="mission-A", artifact_version=2
    )
    assert first.entry_id == second.entry_id
    assert len(outbox.entries()) == 1
    assert first.file_name.endswith(".artifact.json")
    assert (root / "pending" / f"{first.entry_id}.metadata.json").is_file()
    assert outbox.artifact_path(first).is_file()


def test_outbox_prioritizes_urgent_but_preserves_map_delta_dependency_order(tmp_path: Path):
    sender = Sender(fail_versions={2})
    outbox = PersistentOutbox(tmp_path / "uwb_outbox", sender)
    v3 = _delta(tmp_path / "v3.json", 2, 3)
    v2 = _delta(tmp_path / "v2.json", 1, 2)
    urgent = _write(tmp_path / "urgent.json", {
        "mission_id": "mission-A",
        "artifact_version": 3,
        "event_id": "new_victim-1",
        "event_type": "new_victim",
    })
    baseline = _write(tmp_path / "baseline.json", {
        "mission_id": "mission-A", "artifact_version": 1, "result_version": 1
    })
    # Deliberately enqueue out of order.
    outbox.enqueue(v3, artifact_type="map_delta", mission_id="mission-A", artifact_version=3)
    outbox.enqueue(v2, artifact_type="map_delta", mission_id="mission-A", artifact_version=2)
    outbox.enqueue(baseline, artifact_type="semantic_result", mission_id="mission-A", artifact_version=1)
    outbox.enqueue(urgent, artifact_type="urgent_event", mission_id="mission-A", artifact_version=3)

    entries = outbox.entries()
    assert entries[0].artifact_type == "urgent_event"
    delta_versions = [item.result_version for item in entries if item.artifact_type == "map_delta"]
    assert delta_versions == [2, 3]

    outbox.drain()
    called_delta_versions = [call[2] for call in sender.calls if call[0] == "map_delta"]
    assert called_delta_versions == [2]  # v3 is blocked while v2 remains pending.
    assert any(item.artifact_type == "map_delta" and item.artifact_version == 2 for item in outbox.entries())
    assert any(item.artifact_type == "map_delta" and item.artifact_version == 3 for item in outbox.entries())

    recovered = Sender()
    restarted = PersistentOutbox(tmp_path / "uwb_outbox", recovered)
    restarted.drain()
    called_delta_versions = [call[2] for call in recovered.calls if call[0] == "map_delta"]
    assert called_delta_versions == [2, 3]
    assert restarted.entries() == ()
