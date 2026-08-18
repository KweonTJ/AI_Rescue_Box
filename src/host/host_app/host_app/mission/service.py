"""Create a transmission-ready manifest from Host map-editor state."""

from __future__ import annotations

import math
import secrets
from pathlib import Path
from typing import Sequence

from ..map_editor.coordinates import CoordinateTransform, Point
from ..map_editor.importers import ImportedMap
from .models import BaseMapInfo, Entrance, MissionManifest, utc_now


def new_mission_id() -> str:
    return f"mission-{secrets.token_hex(8)}"


def create_manifest(
    *,
    mission_name: str,
    imported_map: ImportedMap,
    transform: CoordinateTransform,
    robot_start_image: Point,
    initial_yaw: float,
    entrance_image_points: Sequence[Point],
    available_teams: int = 0,
    available_rescuers: int = 0,
    mission_id: str | None = None,
    mission_version: int = 1,
    notes: str = "",
) -> MissionManifest:
    robot_start = transform.image_pose_to_map(robot_start_image, initial_yaw)
    entrances = tuple(
        Entrance(
            x=mapped.x,
            y=mapped.y,
            entrance_id=f"entrance-{index + 1}",
            image_x=image_point.x,
            image_y=image_point.y,
        )
        for index, image_point in enumerate(entrance_image_points)
        for mapped in (transform.image_to_map(image_point),)
    )
    transform_data = transform.to_dict()
    transform_data["robot_start_image"] = robot_start_image.to_dict()
    transform_data["initial_image_yaw"] = initial_yaw
    transform_data["initial_map_yaw"] = robot_start.yaw
    normalized_map_yaw = math.atan2(
        math.sin(robot_start.yaw), math.cos(robot_start.yaw)
    )
    transform_data["alignment_convention"] = (
        "image_arrow_aligned_to_map_positive_x"
        if math.isclose(normalized_map_yaw, 0.0, abs_tol=1e-9)
        else "explicit_affine_transform_rotation"
    )
    return MissionManifest(
        mission_id=mission_id or new_mission_id(),
        mission_version=mission_version,
        mission_name=mission_name,
        created_at=utc_now(),
        base_map=BaseMapInfo(
            filename=Path(imported_map.transmission_path).name,
            sha256=imported_map.sha256,
            width=imported_map.width,
            height=imported_map.height,
            format=imported_map.image_format,
        ),
        meters_per_pixel=transform.meters_per_pixel,
        robot_start=robot_start,
        entrances=entrances,
        available_teams=available_teams,
        available_rescuers=available_rescuers,
        coordinate_frame=transform.frame_id,
        coordinate_transform=transform_data,
        notes=notes,
    )
