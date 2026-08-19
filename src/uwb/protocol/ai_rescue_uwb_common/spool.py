"""Safe, atomic spool storage for inbound and outbound artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable

from .protocol import (
    DATA_CHUNK_BYTES,
    DEFAULT_MAX_ARTIFACT_BYTES,
    MAX_METADATA_CHUNKS,
    ArtifactMetadata,
    ProtocolError,
    sha256_file,
)


_TRANSFER_ID_RE = re.compile(r"[0-9a-f]{8}\Z")
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


class SpoolError(RuntimeError):
    """Base class for spool validation and I/O failures."""


class UnsafeFilenameError(SpoolError):
    """A remotely supplied file name could escape or confuse the spool."""


class IncompleteTransferError(SpoolError):
    def __init__(self, missing_indices: Iterable[int]) -> None:
        self.missing_indices = tuple(sorted(set(missing_indices)))
        super().__init__(f"artifact is missing {len(self.missing_indices)} data chunks")


class IntegrityError(SpoolError):
    """The completed file size or SHA-256 differs from its metadata."""


def safe_filename(value: str, *, fallback: str = "artifact.bin") -> str:
    """Return a conservative basename, rejecting path traversal outright."""

    if not isinstance(value, str) or not value or "\x00" in value:
        raise UnsafeFilenameError("file name is empty or contains NUL")
    if value in {".", ".."} or Path(value).name != value or "/" in value or "\\" in value:
        raise UnsafeFilenameError("file name must be a basename without traversal")
    normalized = unicodedata.normalize("NFKC", value).strip()
    normalized = _SAFE_NAME_RE.sub("_", normalized).strip(" .")
    if not normalized or normalized in {".", ".."}:
        normalized = fallback
    if len(normalized.encode("utf-8")) > 180:
        suffix = Path(normalized).suffix[:20]
        stem = Path(normalized).stem[: max(1, 150 - len(suffix))]
        normalized = f"{stem}{suffix}"
    return normalized


def _atomic_json(path: Path, document: dict[str, object]) -> None:
    partial = path.with_name(f".{path.name}.part")
    encoded = json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False).encode(
        "utf-8"
    )
    try:
        with partial.open("wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(partial, path)
    finally:
        partial.unlink(missing_ok=True)


@dataclass(frozen=True)
class CompletedArtifact:
    transfer_id: str
    metadata: ArtifactMetadata
    path: Path
    duplicate_chunks: int


class IncomingArtifact:
    """One disk-backed transfer accepting out-of-order and duplicate chunks."""

    def __init__(
        self,
        manager: "SpoolManager",
        transfer_id: str,
        metadata_chunks: int,
        data_chunks: int,
    ) -> None:
        if _TRANSFER_ID_RE.fullmatch(transfer_id) is None:
            raise SpoolError("invalid transfer ID")
        if metadata_chunks <= 0 or data_chunks <= 0:
            raise SpoolError("chunk counts must be positive")
        if metadata_chunks > MAX_METADATA_CHUNKS:
            raise SpoolError("announced metadata exceeds the configured metadata limit")
        max_chunks = (manager.max_artifact_bytes + DATA_CHUNK_BYTES - 1) // DATA_CHUNK_BYTES
        if data_chunks > max_chunks:
            raise SpoolError("announced data chunk count exceeds the configured limit")
        self.manager = manager
        self.transfer_id = transfer_id
        self.metadata_chunk_count = metadata_chunks
        self.data_chunk_count = data_chunks
        self.metadata: ArtifactMetadata | None = None
        self._metadata_chunks: dict[int, bytes] = {}
        self._received: set[int] = set()
        self._duplicate_chunks = 0
        self._part_path = manager.incoming / f"{transfer_id}.part"
        self._state_path = manager.incoming / f"{transfer_id}.json"
        self._file = None
        self._lock = threading.RLock()
        self._closed = False

    @property
    def duplicate_chunks(self) -> int:
        return self._duplicate_chunks

    @property
    def received_count(self) -> int:
        return len(self._received)

    @property
    def metadata_complete(self) -> bool:
        return self.metadata is not None

    def accept_metadata_chunk(self, index: int, data: bytes) -> None:
        with self._lock:
            self._ensure_open()
            if not 0 <= index < self.metadata_chunk_count:
                raise SpoolError("metadata chunk index is out of range")
            if not data or len(data) > DATA_CHUNK_BYTES:
                raise SpoolError("metadata chunk has an invalid length")
            previous = self._metadata_chunks.get(index)
            if previous is not None:
                if previous != data:
                    raise IntegrityError("duplicate metadata chunk contains different bytes")
                self._duplicate_chunks += 1
                return
            self._metadata_chunks[index] = bytes(data)
            if len(self._metadata_chunks) == self.metadata_chunk_count:
                payload = b"".join(
                    self._metadata_chunks[position]
                    for position in range(self.metadata_chunk_count)
                )
                try:
                    metadata = ArtifactMetadata.from_bytes(payload)
                except ProtocolError as error:
                    raise SpoolError(str(error)) from error
                if metadata.file_size > self.manager.max_artifact_bytes:
                    raise SpoolError("artifact exceeds the configured file-size limit")
                expected = (metadata.file_size + DATA_CHUNK_BYTES - 1) // DATA_CHUNK_BYTES
                if expected != self.data_chunk_count:
                    raise SpoolError("metadata file size does not match START data_chunks")
                self.metadata = metadata
                self._open_partial()
                self._persist_state()

    def _open_partial(self) -> None:
        if self._part_path.exists() or self._state_path.exists():
            raise SpoolError(f"incoming transfer ID already exists: {self.transfer_id}")
        self._file = self._part_path.open("x+b")
        assert self.metadata is not None
        self._file.truncate(self.metadata.file_size)
        self._file.flush()

    def accept_data_chunk(self, index: int, data: bytes) -> None:
        with self._lock:
            self._ensure_open()
            if self.metadata is None or self._file is None:
                raise SpoolError("DATA arrived before complete metadata")
            if not 0 <= index < self.data_chunk_count:
                raise SpoolError("data chunk index is out of range")
            offset = index * DATA_CHUNK_BYTES
            expected_length = min(DATA_CHUNK_BYTES, self.metadata.file_size - offset)
            if len(data) != expected_length:
                raise SpoolError("data chunk length does not match its position")
            if index in self._received:
                self._file.seek(offset)
                if self._file.read(expected_length) != data:
                    raise IntegrityError("duplicate data chunk contains different bytes")
                self._duplicate_chunks += 1
                return
            self._file.seek(offset)
            self._file.write(data)
            self._received.add(index)

    def missing_indices(self) -> tuple[int, ...]:
        with self._lock:
            return tuple(
                index for index in range(self.data_chunk_count) if index not in self._received
            )

    def complete(self) -> CompletedArtifact:
        with self._lock:
            self._ensure_open()
            if self.metadata is None or self._file is None:
                raise SpoolError("metadata is incomplete")
            missing = self.missing_indices()
            if missing:
                raise IncompleteTransferError(missing)
            self._file.flush()
            os.fsync(self._file.fileno())
            self._file.close()
            self._file = None
            actual_size = self._part_path.stat().st_size
            actual_sha = sha256_file(self._part_path)
            if actual_size != self.metadata.file_size or actual_sha != self.metadata.sha256:
                self._move_to_failed("sha256_mismatch")
                self._closed = True
                raise IntegrityError(
                    "completed artifact failed size or SHA-256 verification"
                )

            destination = self.manager._completed_path(self.transfer_id, self.metadata)
            os.replace(self._part_path, destination)
            metadata_path = destination.with_name(f"{destination.name}.metadata.json")
            document = asdict(self.metadata)
            document.update(
                {
                    "transfer_id": self.transfer_id,
                    "verified_sha256": actual_sha,
                    "duplicate_chunks": self._duplicate_chunks,
                }
            )
            _atomic_json(metadata_path, document)
            self._state_path.unlink(missing_ok=True)
            self._closed = True
            return CompletedArtifact(
                transfer_id=self.transfer_id,
                metadata=self.metadata,
                path=destination,
                duplicate_chunks=self._duplicate_chunks,
            )

    def fail(self, reason: str) -> None:
        with self._lock:
            if self._closed:
                return
            if self._file is not None:
                self._file.close()
                self._file = None
            self._move_to_failed(reason)
            self._closed = True

    def _move_to_failed(self, reason: str) -> None:
        safe_reason = _SAFE_NAME_RE.sub("_", reason)[:40] or "failed"
        failed_path = self.manager.failed / f"{self.transfer_id}.{safe_reason}.part"
        if self._part_path.exists():
            os.replace(self._part_path, self.manager._unused_path(failed_path))
        if self._state_path.exists():
            os.replace(
                self._state_path,
                self.manager._unused_path(
                    self.manager.failed / f"{self.transfer_id}.{safe_reason}.json"
                ),
            )

    def _persist_state(self) -> None:
        assert self.metadata is not None
        document = asdict(self.metadata)
        document.update(
            {
                "transfer_id": self.transfer_id,
                "metadata_chunks": self.metadata_chunk_count,
                "data_chunks": self.data_chunk_count,
                "state": "receiving",
            }
        )
        _atomic_json(self._state_path, document)

    def _ensure_open(self) -> None:
        if self._closed:
            raise SpoolError("incoming transfer is already closed")


class SpoolManager:
    """Own the outgoing/incoming/completed/failed directory contract."""

    def __init__(
        self,
        root: Path,
        *,
        max_artifact_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES,
    ) -> None:
        self.root = root.expanduser().resolve()
        if max_artifact_bytes <= 0 or max_artifact_bytes > DEFAULT_MAX_ARTIFACT_BYTES:
            raise SpoolError(
                f"max_artifact_bytes must be 1..{DEFAULT_MAX_ARTIFACT_BYTES}"
            )
        self.max_artifact_bytes = max_artifact_bytes
        self.outgoing = self.root / "outgoing"
        self.incoming = self.root / "incoming"
        self.completed = self.root / "completed"
        self.failed = self.root / "failed"
        for directory in (self.outgoing, self.incoming, self.completed, self.failed):
            directory.mkdir(parents=True, exist_ok=True)

    def stage_outgoing(self, source: Path, metadata: ArtifactMetadata) -> Path:
        """Verify and atomically copy an app-created artifact into outgoing."""

        source = source.expanduser().resolve()
        if not source.is_file():
            raise SpoolError(f"outgoing artifact does not exist: {source}")
        if source.name.endswith(".part"):
            raise SpoolError("outgoing .part files are not ready for transmission")
        if source.stat().st_size != metadata.file_size:
            raise IntegrityError("outgoing artifact size differs from metadata")
        if metadata.file_size > self.max_artifact_bytes:
            raise SpoolError("outgoing artifact exceeds configured size limit")
        if sha256_file(source) != metadata.sha256:
            raise IntegrityError("outgoing artifact SHA-256 differs from metadata")
        if source.parent == self.outgoing:
            return source
        destination = self._unused_path(self.outgoing / safe_filename(metadata.file_name))
        partial = destination.with_name(f".{destination.name}.part")
        try:
            with source.open("rb") as input_stream, partial.open("xb") as output_stream:
                shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)
                output_stream.flush()
                os.fsync(output_stream.fileno())
            os.replace(partial, destination)
        finally:
            partial.unlink(missing_ok=True)
        return destination

    def begin_incoming(
        self, transfer_id: str, metadata_chunks: int, data_chunks: int
    ) -> IncomingArtifact:
        return IncomingArtifact(self, transfer_id, metadata_chunks, data_chunks)

    def _completed_path(self, transfer_id: str, metadata: ArtifactMetadata) -> Path:
        name = safe_filename(metadata.file_name)
        mission = _SAFE_NAME_RE.sub("_", metadata.mission_id)[:64]
        artifact = _SAFE_NAME_RE.sub("_", metadata.artifact_type)[:32]
        candidate = self.completed / mission / f"v{metadata.artifact_version}"
        candidate.mkdir(parents=True, exist_ok=True)
        return self._unused_path(candidate / f"{artifact}_{transfer_id}_{name}")

    @staticmethod
    def _unused_path(candidate: Path) -> Path:
        if not candidate.exists():
            return candidate
        for counter in range(1, 10000):
            alternative = candidate.with_name(
                f"{candidate.stem}_{counter}{candidate.suffix}"
            )
            if not alternative.exists():
                return alternative
        raise SpoolError(f"cannot allocate a unique spool path for {candidate.name}")

    def cleanup_abandoned_parts(
        self, *, age_seconds: float, now: Callable[[], float]
    ) -> int:
        """Move stale .part files to failed; never silently delete evidence."""

        if age_seconds < 0:
            raise SpoolError("age_seconds must be non-negative")
        cutoff = now() - age_seconds
        moved = 0
        for path in self.incoming.glob("*.part"):
            if path.stat().st_mtime <= cutoff:
                destination = self._unused_path(self.failed / f"{path.stem}.abandoned.part")
                os.replace(path, destination)
                state = self.incoming / f"{path.stem}.json"
                if state.exists():
                    os.replace(
                        state,
                        self._unused_path(self.failed / f"{path.stem}.abandoned.json"),
                    )
                moved += 1
        return moved
