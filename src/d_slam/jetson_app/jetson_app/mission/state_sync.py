"""Publish tiny ACTIVE Mission snapshots from Jetson to the command-center Host."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Mapping

from ..domain import utc_now
from ..storage import atomic_write_json
from .manager import MissionManager


class MissionStatePublisher:
    """Maintain a monotonic Mission-state version independent of Mission vN.

    A Mission version can be re-activated after a newer version, so UWB's
    ``artifact_version`` cannot safely reuse ``mission_version``.  The sequence
    below is persisted on Jetson and monotonically increases for every ACTIVE
    selection.
    """

    def __init__(self, manager: MissionManager, transport: Any | None) -> None:
        self.manager = manager
        self.transport = transport
        self._lock = threading.RLock()
        self._root = manager.root.parent / "mission_state"
        self._sequence_path = self._root / "sequence.json"
        self._outgoing = self._root / "outgoing"

    def _next_sequence(self) -> int:
        with self._lock:
            previous = 0
            if self._sequence_path.is_file() and not self._sequence_path.is_symlink():
                try:
                    value = json.loads(self._sequence_path.read_text(encoding="utf-8"))
                    if isinstance(value, Mapping):
                        candidate = value.get("last_artifact_version", 0)
                        if isinstance(candidate, int) and not isinstance(candidate, bool):
                            previous = max(0, candidate)
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    previous = 0
            current = previous + 1
            atomic_write_json(
                self._sequence_path,
                {"last_artifact_version": current, "updated_at": utc_now()},
            )
            return current

    def publish_active(self, mission_id: str, mission_version: int) -> Mapping[str, Any]:
        applied = self.manager.load_mission(mission_id, mission_version)
        artifact_version = self._next_sequence()
        state = {
            "schema_version": "1.0",
            "artifact_type": "mission_state",
            "artifact_version": artifact_version,
            "mission_id": applied.manifest.mission_id,
            "mission_version": applied.manifest.mission_version,
            "state": "ACTIVE",
            "updated_at": utc_now(),
            # The image never crosses UWB.  The canonical manifest is small and
            # lets Host preserve existing result/review/approved-plan storage.
            "manifest": applied.manifest.to_dict(),
        }
        path = self._outgoing / f"mission_state_v{artifact_version}.json"
        atomic_write_json(path, state)

        sender = getattr(self.transport, "send_mission_state", None)
        if not callable(sender):
            return {
                "success": False,
                "state": "local_only",
                "artifact_version": artifact_version,
                "error": "UWB mission-state transport is unavailable",
            }
        result = dict(sender(state, path, priority=180))
        return {
            **result,
            "artifact_version": artifact_version,
            "mission_id": mission_id,
            "mission_version": mission_version,
        }


__all__ = ["MissionStatePublisher"]
