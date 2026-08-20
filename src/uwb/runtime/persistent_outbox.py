"""Disk-backed Jetson UWB outbox with ACK-based removal and restart recovery."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from .ai_boost import ai_boost
from .ports import ArtifactSenderPort


@dataclass(frozen=True)
class OutboxEntry:
    entry_id: str
    artifact_type: str
    mission_id: str
    artifact_version: int
    priority: int
    sha256: str
    file_name: str
    created_at: float
    base_result_version: int | None = None
    result_version: int | None = None
    event_id: str | None = None


class PersistentOutboxError(RuntimeError):
    pass


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(f".{path.name}.{os.getpid()}.part")
    try:
        with part.open("wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(part, path)
    finally:
        part.unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_payload(path: Path) -> Mapping[str, Any]:
    if path.suffix.lower() != ".json":
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, Mapping) else {}


class PersistentOutbox:
    """Persist before radio; remove only after Host application ACK."""

    def __init__(self, root: Path, sender: ArtifactSenderPort) -> None:
        self.root = Path(root).expanduser().resolve()
        self.pending = self.root / "pending"
        self.sender = sender
        self.pending.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    @staticmethod
    def _entry_id(artifact_type: str, mission_id: str, artifact_version: int, sha256: str) -> str:
        identity = f"{artifact_type}|{mission_id}|{int(artifact_version)}|{sha256}"
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:28]

    def enqueue(
        self, source: Path, *, artifact_type: str, mission_id: str,
        artifact_version: int, priority: int = 0,
    ) -> OutboxEntry:
        source = Path(source).expanduser().resolve()
        if not source.is_file() or source.is_symlink():
            raise PersistentOutboxError("outbox source must be a regular file")
        if not mission_id:
            raise PersistentOutboxError("mission_id is required")
        version = int(artifact_version)
        if version < 1:
            raise PersistentOutboxError("artifact_version must be positive")
        payload = _json_payload(source)
        decision = ai_boost(
            artifact_type, payload, requested_priority=priority, enabled=False
        )
        if not decision.transmit:
            raise PersistentOutboxError("AI Boost policy rejected required artifact")
        digest = _sha256(source)
        entry_id = self._entry_id(artifact_type, mission_id, version, digest)
        suffix = source.suffix.lower() or ".bin"
        artifact_path = self.pending / f"{entry_id}.artifact{suffix}"
        metadata_path = self.pending / f"{entry_id}.metadata.json"
        base_result_version = payload.get("base_result_version")
        result_version = payload.get("result_version")
        event_id = payload.get("event_id")
        with self._lock:
            if metadata_path.is_file() and artifact_path.is_file():
                return self._load_entry(metadata_path)
            if metadata_path.exists() or artifact_path.exists():
                raise PersistentOutboxError("partial outbox entry already exists")
            part = artifact_path.with_name(f".{artifact_path.name}.part")
            try:
                with source.open("rb") as input_stream, part.open("xb") as output_stream:
                    shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)
                    output_stream.flush()
                    os.fsync(output_stream.fileno())
                if _sha256(part) != digest:
                    raise PersistentOutboxError("persisted outbox copy failed SHA-256")
                os.replace(part, artifact_path)
            finally:
                part.unlink(missing_ok=True)
            entry = OutboxEntry(
                entry_id=entry_id,
                artifact_type=str(artifact_type),
                mission_id=str(mission_id),
                artifact_version=version,
                priority=decision.priority,
                sha256=digest,
                file_name=artifact_path.name,
                created_at=time.time(),
                base_result_version=(
                    int(base_result_version)
                    if isinstance(base_result_version, int) and not isinstance(base_result_version, bool)
                    else None
                ),
                result_version=(
                    int(result_version)
                    if isinstance(result_version, int) and not isinstance(result_version, bool)
                    else None
                ),
                event_id=str(event_id) if event_id not in {None, ""} else None,
            )
            _atomic_write(
                metadata_path,
                json.dumps(asdict(entry), sort_keys=True, indent=2).encode("utf-8"),
            )
            return entry

    def _load_entry(self, path: Path) -> OutboxEntry:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            entry = OutboxEntry(**value)
        except Exception as error:
            raise PersistentOutboxError(f"invalid outbox metadata {path.name}: {error}") from error
        artifact = self.pending / entry.file_name
        if not artifact.is_file() or artifact.is_symlink():
            raise PersistentOutboxError(f"outbox artifact is missing: {entry.file_name}")
        if _sha256(artifact) != entry.sha256:
            raise PersistentOutboxError(f"outbox artifact SHA-256 mismatch: {entry.entry_id}")
        return entry

    def entries(self) -> tuple[OutboxEntry, ...]:
        with self._lock:
            loaded = [self._load_entry(path) for path in sorted(self.pending.glob("*.metadata.json"))]
            return tuple(sorted(loaded, key=self._sort_key))

    @staticmethod
    def _sort_key(entry: OutboxEntry) -> tuple[Any, ...]:
        if entry.artifact_type == "urgent_event":
            return (0, -entry.priority, entry.created_at, entry.entry_id)
        if entry.artifact_type == "semantic_result":
            return (1, entry.mission_id, entry.artifact_version, entry.created_at)
        if entry.artifact_type == "map_delta":
            return (2, entry.mission_id, entry.result_version or entry.artifact_version, entry.created_at)
        if entry.artifact_type == "map_preview":
            return (4, -entry.priority, entry.created_at, entry.entry_id)
        return (3, -entry.priority, entry.created_at, entry.entry_id)

    def artifact_path(self, entry: OutboxEntry) -> Path:
        return self.pending / entry.file_name

    @staticmethod
    def _acked(result: Mapping[str, Any]) -> bool:
        return bool(result.get("success")) and bool(
            result.get("application_ack") or result.get("application_applied_ack")
        )

    def mark_acked(self, entry: OutboxEntry) -> None:
        with self._lock:
            (self.pending / f"{entry.entry_id}.metadata.json").unlink(missing_ok=True)
            self.artifact_path(entry).unlink(missing_ok=True)

    def send_entry(self, entry: OutboxEntry) -> Mapping[str, Any]:
        result = dict(
            self.sender.send_artifact(
                self.artifact_path(entry), artifact_type=entry.artifact_type,
                mission_id=entry.mission_id, artifact_version=entry.artifact_version,
                priority=entry.priority,
            )
        )
        if self._acked(result):
            self.mark_acked(entry)
        return result

    def drain(self, *, max_entries: int | None = None) -> list[Mapping[str, Any]]:
        outcomes: list[Mapping[str, Any]] = []
        blocked_delta_missions: set[str] = set()
        sent = 0
        for entry in self.entries():
            if max_entries is not None and sent >= max_entries:
                break
            if entry.artifact_type == "map_delta" and entry.mission_id in blocked_delta_missions:
                continue
            try:
                result = self.send_entry(entry)
            except Exception as error:
                result = {
                    "success": False, "state": "pending", "error_code": type(error).__name__,
                    "error_message": str(error), "entry_id": entry.entry_id,
                }
            else:
                result = {**result, "entry_id": entry.entry_id}
            outcomes.append(result)
            sent += 1
            if entry.artifact_type == "map_delta" and not self._acked(result):
                blocked_delta_missions.add(entry.mission_id)
        return outcomes

    def enqueue_and_try_send(
        self, source: Path, *, artifact_type: str, mission_id: str,
        artifact_version: int, priority: int = 0,
    ) -> Mapping[str, Any]:
        entry = self.enqueue(
            source, artifact_type=artifact_type, mission_id=mission_id,
            artifact_version=artifact_version, priority=priority,
        )
        try:
            result = dict(self.send_entry(entry))
        except Exception as error:
            return {
                "success": True, "state": "queued", "delivered": False,
                "entry_id": entry.entry_id, "error_code": type(error).__name__,
                "error_message": str(error), "application_ack": False,
            }
        if self._acked(result):
            return {**result, "state": "delivered", "delivered": True, "entry_id": entry.entry_id}
        return {**result, "success": True, "state": "queued", "delivered": False, "entry_id": entry.entry_id}


__all__ = ["OutboxEntry", "PersistentOutbox", "PersistentOutboxError"]
