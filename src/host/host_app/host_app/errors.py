"""Application-specific errors suitable for API and UI presentation."""


class HostAppError(Exception):
    """Base error for recoverable Host application failures."""


class ValidationError(HostAppError, ValueError):
    """An artifact or user-entered value is invalid."""


class StaleVersionError(ValidationError):
    """An older artifact would replace newer mission state."""


class MapImportError(ValidationError):
    """A selected map is not a supported, valid raster image."""


class BridgeUnavailableError(HostAppError):
    """The local ROS2 UWB Bridge is currently unavailable."""
