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
            raise ProtocolError("metadata is not valid UTF-8 JSON") from error
        if len(payload) > MAX_METADATA_BYTES:
            raise ProtocolError(f"metadata exceeds the {MAX_METADATA_BYTES}-byte limit")
        if not isinstance(document, dict):
            raise ProtocolError("metadata JSON must be an object")
        expected = {
            "artifact_type",
            "mission_id",
            "artifact_version",
            "file_name",
            "file_size",
            "sha256",
            "sender",
            "priority",
            "schema_version",
            "extra",
        }
        if set(document) != expected:
            missing = sorted(expected - set(document))
            unknown = sorted(set(document) - expected)
            raise ProtocolError(f"metadata fields differ: missing={missing}, unknown={unknown}")
        try:
            return cls(**document)
        except TypeError as error:
            raise ProtocolError("metadata field types are invalid") from error


@dataclass(frozen=True)
class StartPacket:
    transfer_id: str
    metadata_chunks: int
    data_chunks: int


@dataclass(frozen=True)
class MetaPacket:
    transfer_id: str
    index: int
    data: bytes


@dataclass(frozen=True)
class DataPacket:
    transfer_id: str
    index: int
    data: bytes


@dataclass(frozen=True)
class EndPacket:
    transfer_id: str


@dataclass(frozen=True)
class AckPacket:
    transfer_id: str
    stage: str


@dataclass(frozen=True)
class NackPacket:
    transfer_id: str
    missing_indices: tuple[int, ...]


@dataclass(frozen=True)
class CancelPacket:
    transfer_id: str
    reason: str = "cancelled"


WirePacket: TypeAlias = (
    StartPacket | MetaPacket | DataPacket | EndPacket | AckPacket | NackPacket | CancelPacket
)


def _validate_chunk(index: int, data: bytes) -> None:
    if not isinstance(index, int) or index < 0 or index >= MAX_CHUNK_COUNT:
        raise ProtocolError("chunk index is outside the supported range")
    if not data or len(data) > DATA_CHUNK_BYTES:
        raise ProtocolError(f"chunk must contain 1..{DATA_CHUNK_BYTES} bytes")


def _encode_line(parts: Iterable[str]) -> bytes:
    try:
        line = ",".join(parts).encode("ascii")
    except UnicodeEncodeError as error:
        raise ProtocolError("wire control fields must be ASCII") from error
    if not line or len(line) > MAX_WIRE_PAYLOAD_BYTES:
        raise ProtocolError(
            f"encoded packet is {len(line)} bytes; maximum is {MAX_WIRE_PAYLOAD_BYTES}"
        )
    if b"\r" in line or b"\n" in line:
        raise ProtocolError("wire packet must contain one line")
    return line


def encode_packet(packet: WirePacket) -> bytes:
    transfer_id = _validate_transfer_id(packet.transfer_id)
    if isinstance(packet, StartPacket):
        if not 1 <= packet.metadata_chunks <= MAX_CHUNK_COUNT:
            raise ProtocolError("metadata_chunks is outside the supported range")
        if not 1 <= packet.data_chunks <= MAX_CHUNK_COUNT:
            raise ProtocolError("data_chunks is outside the supported range")
        return _encode_line(
            (WIRE_PREFIX, "S", transfer_id, str(packet.metadata_chunks), str(packet.data_chunks))
        )
    if isinstance(packet, (MetaPacket, DataPacket)):
        _validate_chunk(packet.index, packet.data)
        kind = "M" if isinstance(packet, MetaPacket) else "D"
        encoded = base64.b64encode(packet.data).decode("ascii")
        return _encode_line((WIRE_PREFIX, kind, transfer_id, str(packet.index), encoded))
    if isinstance(packet, EndPacket):
        return _encode_line((WIRE_PREFIX, "E", transfer_id))
    if isinstance(packet, AckPacket):
        if packet.stage not in ACK_STAGES:
            raise ProtocolError(f"unsupported ACK stage: {packet.stage}")
        return _encode_line((WIRE_PREFIX, "A", transfer_id, packet.stage))
    if isinstance(packet, NackPacket):
        if not packet.missing_indices:
            raise ProtocolError("NACK must list at least one missing chunk")
        if any(index < 0 or index >= MAX_CHUNK_COUNT for index in packet.missing_indices):
            raise ProtocolError("NACK contains an invalid chunk index")
        indices = ";".join(str(index) for index in packet.missing_indices)
        return _encode_line((WIRE_PREFIX, "N", transfer_id, indices))
    if isinstance(packet, CancelPacket):
        if _TOKEN_RE.fullmatch(packet.reason) is None:
            raise ProtocolError("cancel reason must be a lowercase protocol token")
        return _encode_line((WIRE_PREFIX, "C", transfer_id, packet.reason))
    raise TypeError(f"unsupported packet type: {type(packet)!r}")


def _parse_nonnegative_int(
    text: str, field_name: str, *, maximum: int = MAX_CHUNK_COUNT - 1
) -> int:
    if not text or not text.isascii() or not text.isdecimal():
        raise ProtocolError(f"{field_name} must be a non-negative decimal integer")
    value = int(text)
    if value > maximum:
        raise ProtocolError(f"{field_name} is outside the supported range")
    return value


def decode_packet(line: bytes | str) -> WirePacket:
    if isinstance(line, str):
        try:
            raw = line.encode("ascii")
        except UnicodeEncodeError as error:
            raise ProtocolError("wire packet is not ASCII") from error
    else:
        raw = bytes(line)
    if raw.endswith(b"\n"):
        raw = raw[:-1]
    if raw.endswith(b"\r"):
        raw = raw[:-1]
    if not raw or len(raw) > MAX_WIRE_PAYLOAD_BYTES or b"\r" in raw or b"\n" in raw:
        raise ProtocolError("wire packet is empty, oversized, or contains multiple lines")
    try:
        fields = raw.decode("ascii").split(",")
    except UnicodeDecodeError as error:
        raise ProtocolError("wire packet is not ASCII") from error
    if len(fields) < 3 or fields[0] != WIRE_PREFIX:
        raise ProtocolError("wire packet has an unknown prefix")
    kind = fields[1]
    transfer_id = _validate_transfer_id(fields[2])
    if kind == "S" and len(fields) == 5:
        metadata_chunks = _parse_nonnegative_int(
            fields[3], "metadata_chunks", maximum=MAX_CHUNK_COUNT
        )
        data_chunks = _parse_nonnegative_int(
            fields[4], "data_chunks", maximum=MAX_CHUNK_COUNT
        )
        if metadata_chunks == 0 or data_chunks == 0:
            raise ProtocolError("START chunk counts must be positive")
        return StartPacket(transfer_id, metadata_chunks, data_chunks)
    if kind in {"M", "D"} and len(fields) == 5:
        index = _parse_nonnegative_int(fields[3], "chunk index")
        try:
            data = base64.b64decode(fields[4], validate=True)
        except (ValueError, binascii.Error) as error:
            raise ProtocolError("chunk is not valid Base64") from error
        _validate_chunk(index, data)
        packet_type = MetaPacket if kind == "M" else DataPacket
        return packet_type(transfer_id, index, data)
    if kind == "E" and len(fields) == 3:
        return EndPacket(transfer_id)
    if kind == "A" and len(fields) == 4:
        if fields[3] not in ACK_STAGES:
            raise ProtocolError("ACK has an unknown stage")
        return AckPacket(transfer_id, fields[3])
    if kind == "N" and len(fields) == 4:
        if not fields[3]:
            raise ProtocolError("NACK has no missing indices")
        values = tuple(
            _parse_nonnegative_int(value, "missing chunk index")
            for value in fields[3].split(";")
        )
        if len(values) != len(set(values)):
            raise ProtocolError("NACK repeats a missing chunk index")
        return NackPacket(transfer_id, values)
    if kind == "C" and len(fields) == 4:
        if _TOKEN_RE.fullmatch(fields[3]) is None:
            raise ProtocolError("CANCEL has an invalid reason")
        return CancelPacket(transfer_id, fields[3])
    raise ProtocolError("wire packet has an invalid field count or type")


def chunks(payload: bytes, chunk_size: int = DATA_CHUNK_BYTES) -> Iterator[bytes]:
    if chunk_size <= 0 or chunk_size > DATA_CHUNK_BYTES:
        raise ProtocolError(f"chunk_size must be between 1 and {DATA_CHUNK_BYTES}")
    for offset in range(0, len(payload), chunk_size):
        yield payload[offset : offset + chunk_size]


def packetize_metadata(
    transfer_id: str, metadata: ArtifactMetadata
) -> tuple[MetaPacket, ...]:
    _validate_transfer_id(transfer_id)
    return tuple(
        MetaPacket(transfer_id, index, data)
        for index, data in enumerate(chunks(metadata.to_bytes()))
    )


def packetize_file(
    path: Path, metadata: ArtifactMetadata, transfer_id: str | None = None
) -> Iterator[WirePacket]:
    """Yield a complete START/META/DATA/END transfer while detecting mutation."""

    source = path.expanduser().resolve()
    if not source.is_file():
        raise ProtocolError(f"artifact file does not exist: {source}")
    transfer_id = generate_transfer_id() if transfer_id is None else transfer_id
    _validate_transfer_id(transfer_id)
    stat_before = source.stat()
    if stat_before.st_size != metadata.file_size:
        raise ProtocolError("artifact size differs from metadata")
    metadata_packets = packetize_metadata(transfer_id, metadata)
    data_chunk_count = (metadata.file_size + DATA_CHUNK_BYTES - 1) // DATA_CHUNK_BYTES
    yield StartPacket(transfer_id, len(metadata_packets), data_chunk_count)
    yield from metadata_packets

    digest = hashlib.sha256()
    bytes_read = 0
    with source.open("rb") as stream:
        for index in range(data_chunk_count):
            data = stream.read(DATA_CHUNK_BYTES)
            if not data:
                raise ProtocolError("artifact was truncated during packetization")
            digest.update(data)
            bytes_read += len(data)
            yield DataPacket(transfer_id, index, data)
        if stream.read(1):
            raise ProtocolError("artifact grew during packetization")
    stat_after = source.stat()
    if bytes_read != metadata.file_size or digest.hexdigest() != metadata.sha256:
        raise ProtocolError("artifact content differs from metadata")
    if (stat_before.st_mtime_ns, stat_before.st_size) != (
        stat_after.st_mtime_ns,
        stat_after.st_size,
    ):
        raise ProtocolError("artifact changed during packetization")
    yield EndPacket(transfer_id)


def nack_packets(transfer_id: str, missing_indices: Iterable[int]) -> tuple[NackPacket, ...]:
    """Pack an arbitrary missing-index set into valid 111-byte NACK lines."""

    unique = sorted(set(missing_indices))
    if not unique:
        return ()
    result: list[NackPacket] = []
    current: list[int] = []
    for index in unique:
        candidate = NackPacket(transfer_id, tuple((*current, index)))
        try:
            encode_packet(candidate)
        except ProtocolError:
            if not current:
                raise
            result.append(NackPacket(transfer_id, tuple(current)))
            current = [index]
        else:
            current.append(index)
    if current:
        result.append(NackPacket(transfer_id, tuple(current)))
    return tuple(result)


assert MAX_WIRE_PAYLOAD_BYTES == 111
assert len(
    encode_packet(DataPacket("ffffffff", MAX_CHUNK_COUNT - 1, bytes(DATA_CHUNK_BYTES)))
) <= MAX_WIRE_PAYLOAD_BYTES
