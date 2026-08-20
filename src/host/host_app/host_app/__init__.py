"""Core API for the AI Rescue Box Host application."""

from .ai_boost import ai_boost
from .errors import (
    BridgeUnavailableError,
    HostAppError,
    MapImportError,
    StaleVersionError,
    ValidationError,
)

__all__ = [
    "ai_boost",
    "BridgeUnavailableError",
    "HostAppError",
    "MapImportError",
    "StaleVersionError",
    "ValidationError",
]

__version__ = "0.1.0"
