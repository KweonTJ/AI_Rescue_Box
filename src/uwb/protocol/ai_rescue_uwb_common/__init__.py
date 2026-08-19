"""Hardware-independent UWB artifact transport building blocks.

The ESP32 firmware exposes a newline-delimited, acknowledged link with a
maximum application payload of 111 bytes.  This package deliberately contains
no ROS or serial imports so both bridge packages and unit tests can reuse it.
"""

from .bridge import (
    ArtifactBridgeCore,
    BridgeEvent,
    BridgeEventKind,
    BridgeSnapshot,
    OutboundStage,
    TransferResult,
)
from .protocol import (
    ACK_STAGE_APPLIED,
    ACK_STAGE_STORED,
    DATA_CHUNK_BYTES,
    DEFAULT_MAX_ARTIFACT_BYTES,
    MAX_WIRE_PAYLOAD_BYTES,
    AckPacket,
    ArtifactMetadata,
    CancelPacket,
    DataPacket,
    EndPacket,
    MetaPacket,
    NackPacket,
    ProtocolError,
    StartPacket,
    decode_packet,
    encode_packet,
    generate_transfer_id,
    packetize_file,
)
from .spool import (
    CompletedArtifact,
    IncomingArtifact,
    SpoolError,
    SpoolManager,
    UnsafeFilenameError,
    safe_filename,
)
from .transport import (
    FirmwareLineTransport,
    InMemoryEndpoint,
    LineTransport,
    TransportError,
    create_memory_link,
)

__all__ = [
    "ACK_STAGE_APPLIED",
    "ACK_STAGE_STORED",
    "ArtifactBridgeCore",
    "ArtifactMetadata",
    "AckPacket",
    "BridgeEvent",
    "BridgeEventKind",
    "BridgeSnapshot",
    "CancelPacket",
    "CompletedArtifact",
    "DATA_CHUNK_BYTES",
    "DEFAULT_MAX_ARTIFACT_BYTES",
    "DataPacket",
    "EndPacket",
    "FirmwareLineTransport",
    "InMemoryEndpoint",
    "IncomingArtifact",
    "LineTransport",
    "MAX_WIRE_PAYLOAD_BYTES",
    "MetaPacket",
    "NackPacket",
    "OutboundStage",
    "ProtocolError",
    "SpoolError",
    "SpoolManager",
    "StartPacket",
    "TransportError",
    "TransferResult",
    "UnsafeFilenameError",
    "create_memory_link",
    "decode_packet",
    "encode_packet",
    "generate_transfer_id",
    "packetize_file",
    "safe_filename",
]
