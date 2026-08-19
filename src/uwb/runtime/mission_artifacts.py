"""Boundary types and integrity helpers for received mission artifacts."""
from __future__ import annotations

import hashlib
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


def verify_sha256(path: Path, expected: str) -> None:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError("received artifact must be a regular non-symlink file")
    actual = hashlib.sha256(source.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError("received artifact SHA-256 does not match UWB metadata")
