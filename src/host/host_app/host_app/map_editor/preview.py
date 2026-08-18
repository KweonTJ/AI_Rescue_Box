"""Validated geometry metadata for Jetson occupancy-grid PNG previews."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from ..errors import ValidationError


GRID_SIZE_RE = re.compile(r"([1-9][0-9]*)x([1-9][0-9]*)\Z")
MISSION_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")


def _positive_integer(value: object, name: str) -> int:
    if (
        not isinstance(value, str)
        or not value.isascii()
        or not value.isdigit()
        or value.startswith("0")
    ):
        raise ValidationError(
            f"map_preview {name} metadata must be a positive integer"
        )
    result = int(value)
    if result < 1:
        raise ValidationError(
            f"map_preview {name} metadata must be a positive integer"
        )
    return result


def _finite(value: object, name: str, *, positive: bool = False) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValidationError(
            f"map_preview {name} metadata must be numeric"
        ) from error
    if not math.isfinite(result) or (positive and result <= 0):
        qualifier = "positive and finite" if positive else "finite"
        raise ValidationError(f"map_preview {name} metadata must be {qualifier}")
    return result


@dataclass(frozen=True)
class MapPreviewMetadata:
    mission_id: str
    base_map_version: int
    artifact_version: int
    resolution_m_per_cell: float
    origin_x_m: float
    origin_y_m: float
    source_width: int
    source_height: int
    downsample_block: int
    preview_width: int
    preview_height: int

    @property
    def width_m(self) -> float:
        return self.source_width * self.resolution_m_per_cell

    @property
    def height_m(self) -> float:
        return self.source_height * self.resolution_m_per_cell


def read_map_preview_metadata(path: Path) -> MapPreviewMetadata:
    try:
        with Image.open(path) as image:
            if image.format != "PNG":
                raise ValidationError("map_preview must be PNG")
            info = dict(image.info)
            preview_width, preview_height = image.size
            image.verify()
    except ValidationError:
        raise
    except (UnidentifiedImageError, OSError) as error:
        raise ValidationError("map_preview is not a valid PNG") from error
    mission_id = info.get("mission_id")
    if (
        not isinstance(mission_id, str)
        or MISSION_ID_RE.fullmatch(mission_id) is None
    ):
        raise ValidationError(
            "map_preview mission_id metadata is missing or invalid"
        )
    match = GRID_SIZE_RE.fullmatch(str(info.get("source_grid_size", "")))
    if match is None:
        raise ValidationError("map_preview source_grid_size metadata is invalid")
    source_width, source_height = (int(match.group(1)), int(match.group(2)))
    downsample_block = _positive_integer(
        info.get("downsample_block"), "downsample_block"
    )
    expected_width = math.ceil(source_width / downsample_block)
    expected_height = math.ceil(source_height / downsample_block)
    if (preview_width, preview_height) != (expected_width, expected_height):
        raise ValidationError(
            "map_preview pixel dimensions do not match source_grid_size/downsample_block"
        )
    return MapPreviewMetadata(
        mission_id=mission_id,
        base_map_version=_positive_integer(
            info.get("base_map_version"), "base_map_version"
        ),
        artifact_version=_positive_integer(
            info.get("artifact_version"), "artifact_version"
        ),
        resolution_m_per_cell=_finite(
            info.get("resolution_m_per_cell"),
            "resolution_m_per_cell",
            positive=True,
        ),
        origin_x_m=_finite(info.get("origin_x_m"), "origin_x_m"),
        origin_y_m=_finite(info.get("origin_y_m"), "origin_y_m"),
        source_width=source_width,
        source_height=source_height,
        downsample_block=downsample_block,
        preview_width=preview_width,
        preview_height=preview_height,
    )


__all__ = ["MapPreviewMetadata", "read_map_preview_metadata"]
