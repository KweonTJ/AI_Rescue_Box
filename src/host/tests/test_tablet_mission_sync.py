from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

import host_app.api  # installs the business-plan Host extensions
from host_app.mission.workflow import ReceivedArtifactLoader
from host_app.storage import MissionStore


class _Events:
    def __init__(self) -> None:
        self.items = []

    def publish(self, name, payload):
        self.items.append((name, dict(payload)))


class _Owner:
    def __init__(self, root: Path) -> None:
        self.data_root = root
        self.store = MissionStore(root)
        self._storage_lock = threading.RLock()
        self._lock = threading.RLock()
        self.events = _Events()

    def semantic_callback(self, *_args):
        return True


class _Bridge:
    def __init__(self) -> None:
        self.listener = None
        self.acks = []

    def add_received_listener(self, listener):
        self.listener = listener

    def remove_received_listener(self, listener):
        if self.listener == listener:
            self.listener = None

    def acknowledge_artifact(self, transfer_id, applied, error_message):
        self.acks.append((transfer_id, applied, error_message))
        result = Future()
        result.set_result(True)
        return result


def _notice(kind: str, path: Path, mission_id: str = "tablet-test", version: int = 1):
    return SimpleNamespace(
        artifact_kind=kind,
        local_path=path.resolve(),
        file_size=path.stat().st_size,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        mission_id=mission_id,
        artifact_version=version,
        transfer_id=f"{kind}-{version}",
    )


def test_tablet_mission_is_registered_on_host_with_sha_and_duplicate_idempotency(tmp_path: Path):
    received = tmp_path / "received"
    received.mkdir()
    base_map = received / "base_map.png"
    Image.new("RGB", (12, 8), "white").save(base_map)
    map_sha = hashlib.sha256(base_map.read_bytes()).hexdigest()
    manifest = {
        "schema_version": "1.0",
        "mission_id": "tablet-test",
        "mission_version": 1,
        "artifact_version": 1,
        "mission_name": "Tablet Mission",
        "created_at": "2026-08-24T00:00:00Z",
        "base_map": {
            "filename": "base_map.png",
            "sha256": map_sha,
            "width": 12,
            "height": 8,
        },
        "meters_per_pixel": 0.1,
        "robot_start": {"x": 1.0, "y": 1.0, "yaw": 0.2},
        "entrances": [{"x": 0.0, "y": 0.0}],
        "available_teams": 1,
        "available_rescuers": 2,
        "notes": "tablet generated",
        "coordinate_transform": {
            "meters_per_pixel": 0.1,
            "rotation_radians": 0.2,
            "image_origin": {"x": 1.0, "y": 1.0},
        },
        "coordinate_frame": "mission_map",
        "units": "meters",
        "source": "tablet",
        "confidence": 1.0,
    }
    manifest_path = received / "mission_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    owner = _Owner(tmp_path / "host")
    bridge = _Bridge()
    loader = ReceivedArtifactLoader(
        bridge,
        on_semantic_result=owner.semantic_callback,
    )

    loader._load(_notice("base_map", base_map))
    loader._load(_notice("mission_manifest", manifest_path))

    stored = owner.store.load_manifest("tablet-test", 1)
    assert stored.mission_id == "tablet-test"
    assert stored.mission_version == 1
    stored_map = owner.store.mission_dir("tablet-test", 1) / stored.base_map.filename
    assert hashlib.sha256(stored_map.read_bytes()).hexdigest() == map_sha
    assert any(name == "mission.received" for name, _ in owner.events.items)
    assert all(applied for _, applied, _ in bridge.acks)

    # Same version/content is an idempotent duplicate, never a v2 or overwrite.
    loader._load(_notice("base_map", base_map))
    loader._load(_notice("mission_manifest", manifest_path))
    assert owner.store.list_versions("tablet-test") == (1,)
    assert hashlib.sha256(stored_map.read_bytes()).hexdigest() == map_sha
    assert any(name == "mission.duplicate_received" for name, _ in owner.events.items)
    assert all(applied for _, applied, _ in bridge.acks)
