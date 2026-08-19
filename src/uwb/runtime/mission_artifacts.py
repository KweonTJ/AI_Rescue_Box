"""Stage 1 boundary types for pairing received mission artifacts.

Actual Host-to-Jetson mission application is intentionally not wired here; that is Stage 2.
"""
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class ReceivedMissionArtifact:
    transfer_id: str
    artifact_type: str
    mission_id: str
    artifact_version: int
    local_file_path: Path
    sha256: str
