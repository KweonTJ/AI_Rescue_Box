"""Stable cross-package contracts for AI Rescue Box."""

from .coordinates import CoordinateFrame, ObservationState, Transform2D
from .envelope import ArtifactEnvelope, ArtifactType, ContractError
from .versions import VersionVector

__all__ = [
    "ArtifactEnvelope",
    "ArtifactType",
    "ContractError",
    "CoordinateFrame",
    "ObservationState",
    "Transform2D",
    "VersionVector",
]

__version__ = "0.1.0"
