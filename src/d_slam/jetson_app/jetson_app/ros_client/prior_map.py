"""Mission-prior delivery adapter with explicit RTAB-Map capability status."""

from __future__ import annotations

from dataclasses import dataclass
import io
import math
from pathlib import Path
from typing import Callable, Mapping

from PIL import Image, UnidentifiedImageError

from ..domain import MissionManifest, Pose2D
from ..mission.manager import AppliedMission
from ..storage import sha256_file


@dataclass(frozen=True)
class PriorMapDeliveryReport:
    mission_id: str
    mission_version: int
    reference_map: str
    initial_pose: str
    native_rtabmap_prior: str
    message: str

    def to_dict(self) -> dict[str, object]:
        return {
            "mission_id": self.mission_id,
            "mission_version": self.mission_version,
            "reference_map": self.reference_map,
            "initial_pose": self.initial_pose,
            "native_rtabmap_prior": self.native_rtabmap_prior,
            "message": self.message,
        }


@dataclass(frozen=True)
class PriorOccupancyReference:
    width: int
    height: int
    resolution: float
    origin_x: float
    origin_y: float
    origin_yaw: float
    frame_id: str
    data: tuple[int, ...]


def build_prior_occupancy_reference(
    image_bytes: bytes,
    manifest: Mapping[str, object],
    *,
    dark_pixel_threshold: int = 64,
) -> PriorOccupancyReference:
    if not 0 <= dark_pixel_threshold <= 255:
        raise ValueError("dark pixel threshold must be in [0, 255]")
    try:
        with Image.open(io.BytesIO(image_bytes)) as opened:
            grayscale = opened.convert("L")
            width, height = grayscale.size
            pixels = grayscale.tobytes()
    except (OSError, UnidentifiedImageError) as error:
        raise ValueError("prior map bytes are not a valid image") from error
    transform = manifest.get("coordinate_transform")
    if not isinstance(transform, Mapping):
        raise ValueError("mission prior requires coordinate_transform")
    origin = transform.get("image_origin")
    if not isinstance(origin, Mapping):
        raise ValueError("mission prior requires image_origin")
    try:
        scale = float(transform.get("meters_per_pixel"))
        rotation = float(transform.get("rotation_radians", 0.0))
        origin_x = float(origin.get("x"))
        origin_y = float(origin.get("y"))
    except (TypeError, ValueError) as error:
        raise ValueError("mission prior transform must be numeric") from error
    invert_y = transform.get("invert_y", True)
    if not isinstance(invert_y, bool):
        raise ValueError("mission prior invert_y must be boolean")
    if not scale > 0 or not all(
        math.isfinite(value) for value in (scale, rotation, origin_x, origin_y)
    ):
        raise ValueError("mission prior transform is invalid")
    rows = range(height - 1, -1, -1) if invert_y else range(height)
    data = tuple(
        100 if pixels[image_y * width + x] <= dark_pixel_threshold else -1
        for image_y in rows
        for x in range(width)
    )
    image_boundary_x = 0.0
    image_boundary_y = float(height if invert_y else 0)
    dx = (image_boundary_x - origin_x) * scale
    dy = (image_boundary_y - origin_y) * scale
    if invert_y:
        dy = -dy
    cosine, sine = math.cos(rotation), math.sin(rotation)
    return PriorOccupancyReference(
        width=width,
        height=height,
        resolution=scale,
        origin_x=cosine * dx - sine * dy,
        origin_y=sine * dx + cosine * dy,
        origin_yaw=rotation,
        frame_id=str(manifest.get("coordinate_frame", transform.get("frame_id", "map"))),
        data=data,
    )


class PriorMapRosAdapter:
    """Publish a verified prior reference and initial pose through ROS hooks."""

    def __init__(
        self,
        *,
        publish_reference: Callable[[bytes, str, Mapping[str, object]], None] | None,
        publish_initial_pose: Callable[[Pose2D, str], None] | None,
        native_prior_loader: Callable[[Path, MissionManifest], bool] | None = None,
    ) -> None:
        self.publish_reference = publish_reference
        self.publish_initial_pose = publish_initial_pose
        self.native_prior_loader = native_prior_loader
        self.last_report: PriorMapDeliveryReport | None = None

    def apply(self, mission: AppliedMission) -> PriorMapDeliveryReport:
        manifest = mission.manifest
        if sha256_file(mission.base_map_path) != manifest.base_map_sha256:
            raise ValueError("verified prior map changed after mission application")
        reference_state = "disabled"
        initial_pose_state = "disabled"
        native_state = "unavailable"
        messages: list[str] = []
        if self.publish_reference is not None:
            self.publish_reference(
                mission.base_map_path.read_bytes(),
                mission.base_map_path.suffix.lower().lstrip("."),
                manifest.to_dict(),
            )
            reference_state = "published_reference_topic"
        else:
            messages.append("prior reference publisher is disabled or unavailable")
        if self.publish_initial_pose is not None:
            self.publish_initial_pose(manifest.robot_start, manifest.coordinate_frame)
            initial_pose_state = "published"
        else:
            messages.append("initial pose publisher is disabled or unavailable")
        if self.native_prior_loader is not None:
            try:
                native_state = (
                    "loaded" if self.native_prior_loader(mission.base_map_path, manifest)
                    else "rejected"
                )
            except Exception as error:
                native_state = "failed"
                messages.append(f"native prior loader failed: {error}")
        else:
            messages.append(
                "RTAB-Map cannot load a JPEG/PNG as a native database; no feature "
                "alignment or image warp was claimed"
            )
        report = PriorMapDeliveryReport(
            mission_id=manifest.mission_id,
            mission_version=manifest.mission_version,
            reference_map=reference_state,
            initial_pose=initial_pose_state,
            native_rtabmap_prior=native_state,
            message="; ".join(messages) or "prior delivery completed",
        )
        self.last_report = report
        return report


__all__ = [
    "PriorMapDeliveryReport",
    "PriorMapRosAdapter",
    "PriorOccupancyReference",
    "build_prior_occupancy_reference",
]
