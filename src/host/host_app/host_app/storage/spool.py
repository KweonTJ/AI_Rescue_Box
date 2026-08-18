"""Validated app-side UWB spool; the ROS2 Bridge remains the Serial owner."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePath

from ..errors import StaleVersionError, ValidationError
from ..mission.models import positive_int, validate_mission_id
from .atomic import atomic_copy, atomic_write_bytes


ARTIFACT_KINDS = frozenset(
    {
        "base_map",
        "mission_manifest",
        "semantic_result",
        "map_preview",
        "approved_plan",
        "mission_ack",
        "urgent_event",
        "map_delta",
    }
)
TRANSFER_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")


def _safe_name(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValidationError("artifact filename is required")
    path = PurePath(value)
    if path.is_absolute() or len(path.parts) != 1 or value in {".", ".."}:
        raise ValidationError("artifact filename must not contain a path")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class SpoolArtifact:
    artifact_kind: str
    mission_id: str
    artifact_version: int
    path: Path
    file_size: int
    sha256: str


class SpoolManager:
    def __init__(self, data_root: Path, max_file_bytes: int = 10 * 1024 * 1024):
        if max_file_bytes < 1:
            raise ValidationError("max_file_bytes must be positive")
        self.root = Path(data_root).expanduser() / "uwb_spool"
        self.max_file_bytes = max_file_bytes
        self.outgoing = self.root / "outgoing"
        self.incoming = self.root / "incoming"
        self.completed = self.root / "completed"
        self.failed = self.root / "failed"
        for directory in (
            self.outgoing,
            self.incoming,
            self.completed,
            self.failed,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def _validate(self, kind: str, mission_id: str, version: int) -> tuple[str, str, int]:
        if kind not in ARTIFACT_KINDS:
            raise ValidationError(f"unsupported artifact kind: {kind}")
        return kind, validate_mission_id(mission_id), positive_int(version, "artifact_version")

    def stage_outgoing(
        self,
        source: Path,
        artifact_kind: str,
        mission_id: str,
        artifact_version: int,
    ) -> SpoolArtifact:
        kind, mission_id, version = self._validate(
            artifact_kind, mission_id, artifact_version
        )
        source = Path(source).expanduser()
        if not source.is_file():
            raise ValidationError("outgoing artifact does not exist")
        file_size = source.stat().st_size
        if file_size < 1 or file_size > self.max_file_bytes:
            raise ValidationError("outgoing artifact size is outside the allowed range")
        suffix = source.suffix.lower()
        if suffix not in {".json", ".jpg", ".jpeg", ".png"}:
            raise ValidationError("artifact must be JSON, JPEG, or PNG")
        filename = f"{mission_id}_{kind}_v{version}{suffix}"
        destination = self.outgoing / filename
        try:
            atomic_copy(source, destination)
        except FileExistsError as error:
            raise StaleVersionError("outgoing artifact is already staged") from error
        return SpoolArtifact(
            artifact_kind=kind,
            mission_id=mission_id,
            artifact_version=version,
            path=destination,
            file_size=file_size,
            sha256=_sha256(destination),
        )

    def incoming_part_path(self, transfer_id: str, filename: str) -> Path:
        if not isinstance(transfer_id, str) or TRANSFER_ID_RE.fullmatch(transfer_id) is None:
            raise ValidationError("invalid transfer_id")
        filename = _safe_name(filename)
        return self.incoming / f"{transfer_id}_{filename}.part"

    def write_incoming_part(self, transfer_id: str, filename: str, content: bytes) -> Path:
        if len(content) > self.max_file_bytes:
            raise ValidationError("incoming artifact exceeds the allowed size")
        path = self.incoming_part_path(transfer_id, filename)
        return atomic_write_bytes(path, content)

    def finalize_incoming(
        self,
        transfer_id: str,
        filename: str,
        expected_sha256: str,
    ) -> Path:
        part = self.incoming_part_path(transfer_id, filename)
        if not part.is_file():
            raise ValidationError("incoming partial artifact does not exist")
        actual_sha256 = _sha256(part)
        destination_name = f"{transfer_id}_{_safe_name(filename)}"
        if actual_sha256 != expected_sha256:
            failed = self.failed / destination_name
            os.replace(part, failed)
            raise ValidationError("incoming artifact SHA-256 mismatch")
        completed = self.completed / destination_name
        if completed.exists():
            raise StaleVersionError("incoming artifact was already completed")
        os.replace(part, completed)
        return completed
