"""Versioned artifact protocol carried by the legacy ESP32 line bridge.

Every encoded packet is at most 111 bytes.  The limit is not a DW1000 guess:
the checked-in firmware allocates a 120-byte radio frame and consumes nine
bytes for its link header.  Binary content is split into 66-byte chunks so a
six-digit chunk index and Base64 data still fit in that envelope.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import secrets
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, TypeAlias


PROTOCOL_VERSION = 1
WIRE_PREFIX = "@A"
MAX_UWB_FRAME_BYTES = 120
FIRMWARE_FRAME_HEADER_BYTES = 9
MAX_WIRE_PAYLOAD_BYTES = MAX_UWB_FRAME_BYTES - FIRMWARE_FRAME_HEADER_BYTES
DATA_CHUNK_BYTES = 66
DEFAULT_MAX_ARTIFACT_BYTES = 10 * 1024 * 1024
MAX_CHUNK_COUNT = (DEFAULT_MAX_ARTIFACT_BYTES + DATA_CHUNK_BYTES - 1) // DATA_CHUNK_BYTES
MAX_METADATA_BYTES = 64 * 1024
MAX_METADATA_CHUNKS = (MAX_METADATA_BYTES + DATA_CHUNK_BYTES - 1) // DATA_CHUNK_BYTES

ACK_STAGE_STORED = "stored"
ACK_STAGE_APPLIED = "applied"
ACK_STAGES = frozenset({ACK_STAGE_STORED, ACK_STAGE_APPLIED})
KNOWN_ARTIFACT_TYPES = frozenset(
    {
        "base_map",
        "mission_manifest",
        "semantic_result",
        "map_preview",
        "approved_plan",
        "mission_ack",
        "urgent_event",
        "map_delta",
        "mission_state",
    }
)

_TRANSFER_ID_RE = re.compile(r"[0-9a-f]{8}\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_TOKEN_RE = re.compile(r"[a-z][a-z0-9_]{0,31}\Z")
_MISSION_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_SENDER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,31}\Z")


class ProtocolError(ValueError):
    """A packet or artifact metadata value violates the wire protocol."""


def _validate_transfer_id(transfer_id: str) -> str:
    if _TRANSFER_ID_RE.fullmatch(transfer_id) is None:
        raise ProtocolError("transfer_id must be eight lowercase hexadecimal characters")
    return transfer_id


def generate_transfer_id() -> str:
    return secrets.token_hex(4)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class ArtifactMetadata:
    """Validated metadata announced before an artifact body."""

    artifact_type: str
    mission_id: str
    artifact_version: int
    file_name: str
    file_size: int
    sha256: str
    sender: str
    priority: int = 100
    schema_version: int = 1
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if _TOKEN_RE.fullmatch(self.artifact_type) is None:
            raise ProtocolError("artifact_type must be a lowercase protocol token")
        if self.artifact_type not in KNOWN_ARTIFACT_TYPES:
            allowed = ", ".join(sorted(KNOWN_ARTIFACT_TYPES))
            raise ProtocolError(f"unsupported artifact_type; expected one of: {allowed}")
        if _MISSION_ID_RE.fullmatch(self.mission_id) is None:
            raise ProtocolError("mission_id contains unsupported characters")
        if (
            isinstance(self.artifact_version, bool)
            or not isinstance(self.artifact_version, int)
            or self.artifact_version <= 0
        ):
            raise ProtocolError("artifact_version must be a positive integer")
        if not self.file_name or self.file_name in {".", ".."}:
            raise ProtocolError("file_name is empty or unsafe")
        if Path(self.file_name).name != self.file_name or "\x00" in self.file_name:
            raise ProtocolError("file_name must not contain a path")
        if not isinstance(self.file_size, int) or self.file_size <= 0:
            raise ProtocolError("file_size must be greater than zero")
        if self.file_size > DEFAULT_MAX_ARTIFACT_BYTES:
            raise ProtocolError(
                f"file_size exceeds the default {DEFAULT_MAX_ARTIFACT_BYTES}-byte limit"
            )
        if _SHA256_RE.fullmatch(self.sha256) is None:
            raise ProtocolError("sha256 must be 64 lowercase hexadecimal characters")
        if _SENDER_RE.fullmatch(self.sender) is None:
            raise ProtocolError("sender contains unsupported characters")
        if not isinstance(self.priority, int) or not 0 <= self.priority <= 255:
            raise ProtocolError("priority must be between 0 and 255")
        if not isinstance(self.schema_version, int) or self.schema_version <= 0:
            raise ProtocolError("schema_version must be a positive integer")
        if not isinstance(self.extra, Mapping):
            raise ProtocolError("extra metadata must be an object")
        try:
            json.dumps(dict(self.extra), allow_nan=False)
        except (TypeError, ValueError) as error:
            raise ProtocolError("extra metadata is not JSON serializable") from error

    @classmethod
    def from_file(
        cls,
        path: Path,
        *,
        artifact_type: str,
        mission_id: str,
        artifact_version: int,
        sender: str,
        priority: int = 100,
        schema_version: int = 1,
        extra: Mapping[str, Any] | None = None,
    ) -> "ArtifactMetadata":
        source = path.expanduser().resolve()
        if not source.is_file():
            raise ProtocolError(f"artifact file does not exist: {source}")
        size = source.stat().st_size
        return cls(
            artifact_type=artifact_type,
            mission_id=mission_id,
            artifact_version=artifact_version,
            file_name=source.name,
            file_size=size,
            sha256=sha256_file(source),
            sender=sender,
            priority=priority,
            schema_version=schema_version,
            extra={} if extra is None else dict(extra),
        )

    def to_bytes(self) -> bytes:
        document = asdict(self)
        document["extra"] = dict(self.extra)
        encoded = json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        if len(encoded) > MAX_METADATA_BYTES:
            raise ProtocolError(
                f"encoded metadata exceeds the {MAX_METADATA_BYTES}-byte limit"
            )
        return encoded

    @classmethod
    def from_bytes(cls, payload: bytes) -> "ArtifactMetadata":
        try:
            document = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProtocolError("artifact metadata is not valid UTF-8 JSON") from error
        if not isinstance(document, Mapping):
            raise ProtocolError("artifact metadata must be a JSON object")
        try:
            return cls(**document)
        except TypeError as error:
            raise ProtocolError("artifact metadata contains invalid fields") from error


@dataclass(frozen=True)
class StartPacket:
    transfer_id: str
    metadata_size: int
    metadata_chunks: int


@dataclass(frozen=True)
class MetadataPacket:
    transfer_id: str
    chunk_index: int
    data: bytes


@dataclass(frozen=True)
class DataPacket:
    transfer_id: str
    chunk_index: int
    data: bytes


@dataclass(frozen=True)
class EndPacket:
    transfer_id: str
    chunk_count: int


@dataclass(frozen=True)
class AckPacket:
    transfer_id: str
    stage: str
    success: bool
    detail: str = ""


@dataclass(frozen=True)
class MissingPacket:
    transfer_id: str
    chunk_indices: tuple[int, ...]


@dataclass(frozen=True)
class CancelPacket:
    transfer_id: str


WirePacket: TypeAlias = (
    StartPacket
    | MetadataPacket
    | DataPacket
    | EndPacket
    | AckPacket
    | MissingPacket
    | CancelPacket
)


def _b64_encode(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _b64_decode(data: str) -> bytes:
    try:
        return base64.b64decode(data.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error) as error:
        raise ProtocolError("invalid Base64 data") from error


def _positive_index(value: int, name: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < maximum:
        raise ProtocolError(f"{name} is outside the allowed range")
    return value


def _encode_packet(packet: WirePacket) -> str:
    if isinstance(packet, StartPacket):
        _validate_transfer_id(packet.transfer_id)
        if not 0 < packet.metadata_size <= MAX_METADATA_BYTES:
            raise ProtocolError("metadata_size is outside the allowed range")
        if not 0 < packet.metadata_chunks <= MAX_METADATA_CHUNKS:
            raise ProtocolError("metadata_chunks is outside the allowed range")
        fields = [
            WIRE_PREFIX,
            "S",
            packet.transfer_id,
            str(packet.metadata_size),
            str(packet.metadata_chunks),
        ]
    elif isinstance(packet, MetadataPacket):
        _validate_transfer_id(packet.transfer_id)
        _positive_index(packet.chunk_index, "metadata chunk_index", MAX_METADATA_CHUNKS)
        if not packet.data or len(packet.data) > DATA_CHUNK_BYTES:
            raise ProtocolError("metadata chunk data is outside the allowed range")
        fields = [WIRE_PREFIX, "M", packet.transfer_id, str(packet.chunk_index), _b64_encode(packet.data)]
    elif isinstance(packet, DataPacket):
        _validate_transfer_id(packet.transfer_id)
        _positive_index(packet.chunk_index, "data chunk_index", MAX_CHUNK_COUNT)
        if not packet.data or len(packet.data) > DATA_CHUNK_BYTES:
            raise ProtocolError("data chunk data is outside the allowed range")
        fields = [WIRE_PREFIX, "D", packet.transfer_id, str(packet.chunk_index), _b64_encode(packet.data)]
    elif isinstance(packet, EndPacket):
        _validate_transfer_id(packet.transfer_id)
        if not 0 <= packet.chunk_count <= MAX_CHUNK_COUNT:
            raise ProtocolError("chunk_count is outside the allowed range")
        fields = [WIRE_PREFIX, "E", packet.transfer_id, str(packet.chunk_count)]
    elif isinstance(packet, AckPacket):
        _validate_transfer_id(packet.transfer_id)
        if packet.stage not in ACK_STAGES:
            raise ProtocolError("ack stage is unsupported")
        fields = [
            WIRE_PREFIX,
            "A",
            packet.transfer_id,
            packet.stage,
            "1" if packet.success else "0",
            _b64_encode(packet.detail.encode("utf-8")) if packet.detail else "-",
        ]
    elif isinstance(packet, MissingPacket):
        _validate_transfer_id(packet.transfer_id)
        if not packet.chunk_indices:
            raise ProtocolError("missing chunk list must not be empty")
        for value in packet.chunk_indices:
            _positive_index(value, "missing chunk_index", MAX_CHUNK_COUNT)
        fields = [
            WIRE_PREFIX,
            "R",
            packet.transfer_id,
            ",".join(str(value) for value in packet.chunk_indices),
        ]
    elif isinstance(packet, CancelPacket):
        _validate_transfer_id(packet.transfer_id)
        fields = [WIRE_PREFIX, "C", packet.transfer_id]
    else:  # pragma: no cover - exhaustive type guard
        raise ProtocolError("unsupported packet type")
    encoded = "|".join(fields)
    if len(encoded.encode("utf-8")) > MAX_WIRE_PAYLOAD_BYTES:
        raise ProtocolError("encoded packet exceeds firmware payload capacity")
    return encoded


def encode_packet(packet: WirePacket) -> bytes:
    return (_encode_packet(packet) + "\n").encode("utf-8")


def decode_packet(line: bytes | str) -> WirePacket:
    text = line.decode("utf-8") if isinstance(line, bytes) else str(line)
    text = text.rstrip("\r\n")
    if not text.startswith(f"{WIRE_PREFIX}|"):
        raise ProtocolError("packet prefix is invalid")
    fields = text.split("|")
    if len(fields) < 3:
        raise ProtocolError("packet is truncated")
    packet_type = fields[1]
    transfer_id = _validate_transfer_id(fields[2])
    try:
        if packet_type == "S" and len(fields) == 5:
            return StartPacket(transfer_id, int(fields[3]), int(fields[4]))
        if packet_type == "M" and len(fields) == 5:
            return MetadataPacket(transfer_id, int(fields[3]), _b64_decode(fields[4]))
        if packet_type == "D" and len(fields) == 5:
            return DataPacket(transfer_id, int(fields[3]), _b64_decode(fields[4]))
        if packet_type == "E" and len(fields) == 4:
            return EndPacket(transfer_id, int(fields[3]))
        if packet_type == "A" and len(fields) == 6:
            if fields[4] not in {"0", "1"}:
                raise ProtocolError("ack success flag is invalid")
            detail = "" if fields[5] == "-" else _b64_decode(fields[5]).decode("utf-8")
            return AckPacket(transfer_id, fields[3], fields[4] == "1", detail)
        if packet_type == "R" and len(fields) == 4:
            indices = tuple(int(value) for value in fields[3].split(",") if value)
            return MissingPacket(transfer_id, indices)
        if packet_type == "C" and len(fields) == 3:
            return CancelPacket(transfer_id)
    except (ValueError, UnicodeDecodeError) as error:
        raise ProtocolError("packet contains malformed fields") from error
    raise ProtocolError("packet type or field count is invalid")


def metadata_packets(metadata: ArtifactMetadata, transfer_id: str) -> tuple[StartPacket, tuple[MetadataPacket, ...]]:
    _validate_transfer_id(transfer_id)
    payload = metadata.to_bytes()
    chunks = tuple(
        MetadataPacket(transfer_id, index, payload[offset : offset + DATA_CHUNK_BYTES])
        for index, offset in enumerate(range(0, len(payload), DATA_CHUNK_BYTES))
    )
    return StartPacket(transfer_id, len(payload), len(chunks)), chunks


def data_packets(path: Path, transfer_id: str) -> Iterator[DataPacket]:
    _validate_transfer_id(transfer_id)
    with Path(path).open("rb") as source:
        index = 0
        while block := source.read(DATA_CHUNK_BYTES):
            if index >= MAX_CHUNK_COUNT:
                raise ProtocolError("artifact exceeds supported chunk count")
            yield DataPacket(transfer_id, index, block)
            index += 1


def packet_lines(packets: Iterable[WirePacket]) -> Iterator[bytes]:
    for packet in packets:
        yield encode_packet(packet)
