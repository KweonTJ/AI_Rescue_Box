"""Communication-only pairing and verification state for received mission artifacts.

This module deliberately does not apply a mission to any sensor, SLAM or analysis
implementation. Application handoff remains a later-stage concern.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .mission_artifacts import ReceivedMissionArtifact


@dataclass(frozen=True)
class MissionArtifactPair:
    mission_id: str
    artifact_version: int
    manifest: ReceivedMissionArtifact
    base_map: ReceivedMissionArtifact


class MissionArtifactCoordinator:
    def __init__(self) -> None:
        self._pending: dict[tuple[str, int], dict[str, ReceivedMissionArtifact]] = {}

    def observe(self, artifact: ReceivedMissionArtifact) -> MissionArtifactPair | None:
        if artifact.artifact_type not in {"mission_manifest", "base_map"}:
            return None
        key = (artifact.mission_id, artifact.artifact_version)
        bucket = self._pending.setdefault(key, {})
        previous = bucket.get(artifact.artifact_type)
        if previous is not None and previous.sha256 != artifact.sha256:
            raise ValueError(
                f"conflicting {artifact.artifact_type} for {artifact.mission_id} "
                f"v{artifact.artifact_version}"
            )
        bucket[artifact.artifact_type] = artifact
        manifest = bucket.get("mission_manifest")
        base_map = bucket.get("base_map")
        if manifest is None or base_map is None:
            return None
        return MissionArtifactPair(
            mission_id=artifact.mission_id,
            artifact_version=artifact.artifact_version,
            manifest=manifest,
            base_map=base_map,
        )

    def forget(self, mission_id: str, artifact_version: int) -> None:
        self._pending.pop((mission_id, artifact_version), None)
