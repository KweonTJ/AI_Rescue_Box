"""Core API for the AI Rescue Box Host application."""

from .errors import (
    BridgeUnavailableError,
    HostAppError,
    MapImportError,
    StaleVersionError,
    ValidationError,
)

__all__ = [
    "BridgeUnavailableError",
    "HostAppError",
    "MapImportError",
    "StaleVersionError",
    "ValidationError",
]

__version__ = "0.1.0"
