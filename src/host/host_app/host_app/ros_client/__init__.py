"""Host-facing UWB bridge adapters.

``SerialBridgeClient`` is the Windows product default. ``RclpyBridgeClient``
remains an optional development adapter for an already prepared ROS 2 host.
"""

from .bridge_client import (
    ArtifactRequest,
    BridgeClient,
    BridgeConnectionState,
    BridgeStatus,
    HostBridgeFacade,
    OfflineBridgeClient,
    ReceivedArtifactNotice,
    RclpyBridgeClient,
    SendFeedback,
    SendResult,
)
from .serial_client import SerialBridgeClient

__all__ = [
    "ArtifactRequest",
    "BridgeClient",
    "BridgeConnectionState",
    "BridgeStatus",
    "HostBridgeFacade",
    "OfflineBridgeClient",
    "ReceivedArtifactNotice",
    "RclpyBridgeClient",
    "SendFeedback",
    "SendResult",
    "SerialBridgeClient",
]
