"""Raster import and image/map coordinate conversion."""

from .coordinates import CoordinateTransform, Point, Pose, calculate_scale
from .importers import ImportedMap, MapImporter, NormalizationOptions, RasterMapImporter
from .preview import MapPreviewMetadata, read_map_preview_metadata

__all__ = [
    "CoordinateTransform",
    "ImportedMap",
    "MapImporter",
    "NormalizationOptions",
    "Point",
    "Pose",
    "RasterMapImporter",
    "MapPreviewMetadata",
    "calculate_scale",
    "read_map_preview_metadata",
]
