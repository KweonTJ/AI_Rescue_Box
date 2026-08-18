"""Explicit conversion between raster coordinates and a metric map frame."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..errors import ValidationError


def _finite(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValidationError(f"{name} must be numeric") from error
    if not math.isfinite(result):
        raise ValidationError(f"{name} must be finite")
    return result


@dataclass(frozen=True)
class Point:
    x: float
    y: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "x", _finite(self.x, "x"))
        object.__setattr__(self, "y", _finite(self.y, "y"))

    @classmethod
    def from_value(cls, value: Any, name: str = "point") -> "Point":
        if isinstance(value, cls):
            return value
        if isinstance(value, Mapping) and "x" in value and "y" in value:
            return cls(value["x"], value["y"])
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            if len(value) == 2:
                return cls(value[0], value[1])
        raise ValidationError(f"{name} must contain x and y")

    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y}


@dataclass(frozen=True)
class Pose(Point):
    yaw: float = 0.0

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "yaw", _finite(self.yaw, "yaw"))

    @classmethod
    def from_value(cls, value: Any, name: str = "pose") -> "Pose":
        if isinstance(value, cls):
            return value
        if isinstance(value, Mapping) and "x" in value and "y" in value:
            return cls(value["x"], value["y"], value.get("yaw", 0.0))
        raise ValidationError(f"{name} must contain x, y, and optional yaw")

    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "yaw": self.yaw}


def calculate_scale(first: Point, second: Point, real_distance_m: float) -> float:
    distance = _finite(real_distance_m, "real_distance_m")
    if distance <= 0:
        raise ValidationError("real_distance_m must be positive")
    pixels = math.hypot(second.x - first.x, second.y - first.y)
    if pixels <= 0:
        raise ValidationError("scale points must be different")
    return distance / pixels


@dataclass(frozen=True)
class CoordinateTransform:
    """Affine image↔map transform anchored at an image-space origin."""

    image_origin: Point
    meters_per_pixel: float
    rotation_radians: float = 0.0
    invert_y: bool = True
    frame_id: str = "mission_map"

    def __post_init__(self) -> None:
        scale = _finite(self.meters_per_pixel, "meters_per_pixel")
        rotation = _finite(self.rotation_radians, "rotation_radians")
        if scale <= 0:
            raise ValidationError("meters_per_pixel must be positive")
        if not isinstance(self.invert_y, bool):
            raise ValidationError("invert_y must be boolean")
        if not isinstance(self.frame_id, str) or not self.frame_id.strip():
            raise ValidationError("frame_id is required")
        object.__setattr__(self, "meters_per_pixel", scale)
        object.__setattr__(self, "rotation_radians", rotation)

    def image_to_map(self, point: Point) -> Point:
        dx = (point.x - self.image_origin.x) * self.meters_per_pixel
        dy = (point.y - self.image_origin.y) * self.meters_per_pixel
        if self.invert_y:
            dy = -dy
        cosine = math.cos(self.rotation_radians)
        sine = math.sin(self.rotation_radians)
        return Point(cosine * dx - sine * dy, sine * dx + cosine * dy)

    def map_to_image(self, point: Point) -> Point:
        cosine = math.cos(self.rotation_radians)
        sine = math.sin(self.rotation_radians)
        dx = cosine * point.x + sine * point.y
        dy = -sine * point.x + cosine * point.y
        if self.invert_y:
            dy = -dy
        return Point(
            self.image_origin.x + dx / self.meters_per_pixel,
            self.image_origin.y + dy / self.meters_per_pixel,
        )

    def image_pose_to_map(self, point: Point, image_yaw: float) -> Pose:
        yaw = _finite(image_yaw, "image_yaw")
        if self.invert_y:
            yaw = -yaw
        mapped = self.image_to_map(point)
        return Pose(mapped.x, mapped.y, yaw + self.rotation_radians)

    def to_dict(self) -> dict[str, Any]:
        return {
            "image_origin": self.image_origin.to_dict(),
            "meters_per_pixel": self.meters_per_pixel,
            "rotation_radians": self.rotation_radians,
            "invert_y": self.invert_y,
            "frame_id": self.frame_id,
            "image_y_axis": "down",
            "map_y_axis": "up" if self.invert_y else "down",
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CoordinateTransform":
        return cls(
            image_origin=Point.from_value(value.get("image_origin"), "image_origin"),
            meters_per_pixel=value.get("meters_per_pixel"),
            rotation_radians=value.get("rotation_radians", 0.0),
            invert_y=value.get("invert_y", True),
            frame_id=value.get("frame_id", "mission_map"),
        )
