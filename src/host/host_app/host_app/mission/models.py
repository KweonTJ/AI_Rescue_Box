"""Versioned JSON models shared over UWB with the Jetson application."""

from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import PurePath
from typing import Any, Mapping, Sequence

from ..errors import ValidationError
from ..map_editor.coordinates import CoordinateTransform, Point, Pose


SCHEMA_VERSION = "1.0"
MISSION_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_timestamp(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValidationError(f"{name} must be a timezone-aware ISO-8601 string")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise ValidationError(f"{name} is not valid ISO-8601") from error
    if parsed.tzinfo is None:
        raise ValidationError(f"{name} must include a timezone")
    return value


def validate_mission_id(value: Any) -> str:
    if not isinstance(value, str) or MISSION_ID_RE.fullmatch(value) is None:
        raise ValidationError(
            "mission_id must be 1-64 safe ASCII letters, digits, '.', '_' or '-'"
        )
    return value


def positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValidationError(f"{name} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise ValidationError(f"{name} must be a positive integer") from error
    if parsed < 1 or parsed != value:
        raise ValidationError(f"{name} must be a positive integer")
    return parsed


def nonnegative_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValidationError(f"{name} must be a non-negative integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise ValidationError(f"{name} must be a non-negative integer") from error
    if parsed < 0 or parsed != value:
        raise ValidationError(f"{name} must be a non-negative integer")
    return parsed


def confidence(value: Any, name: str = "confidence") -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise ValidationError(f"{name} must be numeric") from error
    if not math.isfinite(parsed) or not 0 <= parsed <= 1:
        raise ValidationError(f"{name} must be between 0 and 1")
    return parsed


def safe_filename(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValidationError("base map filename is required")
    path = PurePath(value)
    if path.is_absolute() or len(path.parts) != 1 or value in {".", ".."}:
        raise ValidationError("base map filename must not contain a path")
    if path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
        raise ValidationError("base map must be JPEG or PNG")
    return value


@dataclass(frozen=True)
class BaseMapInfo:
    filename: str
    sha256: str
    width: int
    height: int
    format: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "filename", safe_filename(self.filename))
        if not isinstance(self.sha256, str) or SHA256_RE.fullmatch(self.sha256) is None:
            raise ValidationError("base map SHA-256 must be 64 lowercase hex characters")
        object.__setattr__(self, "width", positive_int(self.width, "base map width"))
        object.__setattr__(self, "height", positive_int(self.height, "base map height"))
        if self.format is not None and self.format not in {"JPEG", "PNG"}:
            raise ValidationError("base map format must be JPEG or PNG")

    @classmethod
    def from_value(cls, value: Mapping[str, Any]) -> "BaseMapInfo":
        if not isinstance(value, Mapping):
            raise ValidationError("base_map must be an object")
        return cls(
            filename=value.get("filename"),
            sha256=value.get("sha256"),
            width=value.get("width"),
            height=value.get("height"),
            format=value.get("format"),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "filename": self.filename,
            "sha256": self.sha256,
            "width": self.width,
            "height": self.height,
        }
        if self.format is not None:
            result["format"] = self.format
        return result


@dataclass(frozen=True)
class Entrance:
    x: float
    y: float
    entrance_id: str | None = None
    image_x: float | None = None
    image_y: float | None = None

    def __post_init__(self) -> None:
        point = Point(self.x, self.y)
        object.__setattr__(self, "x", point.x)
        object.__setattr__(self, "y", point.y)
        if self.entrance_id is not None and not str(self.entrance_id).strip():
            raise ValidationError("entrance_id cannot be empty")
        if (self.image_x is None) != (self.image_y is None):
            raise ValidationError("image_x and image_y must be provided together")
        if self.image_x is not None:
            image_point = Point(self.image_x, self.image_y)
            object.__setattr__(self, "image_x", image_point.x)
            object.__setattr__(self, "image_y", image_point.y)

    @classmethod
    def from_value(cls, value: Any) -> "Entrance":
        if not isinstance(value, Mapping):
            point = Point.from_value(value, "entrance")
            return cls(point.x, point.y)
        x = value.get("x", value.get("map_x"))
        y = value.get("y", value.get("map_y"))
        return cls(
            x=x,
            y=y,
            entrance_id=value.get("entrance_id", value.get("id")),
            image_x=value.get("image_x"),
            image_y=value.get("image_y"),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "x": self.x,
            "y": self.y,
            "map_x": self.x,
            "map_y": self.y,
        }
        if self.entrance_id is not None:
            result["id"] = self.entrance_id
        if self.image_x is not None:
            result.update({"image_x": self.image_x, "image_y": self.image_y})
        return result


@dataclass(frozen=True)
class MissionManifest:
    mission_id: str
    mission_version: int
    mission_name: str
    created_at: str
    base_map: BaseMapInfo
    meters_per_pixel: float
    robot_start: Pose
    entrances: tuple[Entrance, ...]
    available_teams: int = 0
    available_rescuers: int = 0
    coordinate_frame: str = "mission_map"
    notes: str = ""
    coordinate_transform: Mapping[str, Any] = field(default_factory=dict)
    source: str = "host"
    confidence: float = 1.0
    units: str = "meters"
    schema_version: str = SCHEMA_VERSION
    artifact_version: int | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValidationError(f"schema_version must be {SCHEMA_VERSION}")
        object.__setattr__(self, "mission_id", validate_mission_id(self.mission_id))
        version = positive_int(self.mission_version, "mission_version")
        object.__setattr__(self, "mission_version", version)
        artifact_version = version if self.artifact_version is None else self.artifact_version
        artifact_version = positive_int(artifact_version, "artifact_version")
        if artifact_version != version:
            raise ValidationError("artifact_version must match mission_version")
        object.__setattr__(self, "artifact_version", artifact_version)
        if not isinstance(self.mission_name, str) or not self.mission_name.strip():
            raise ValidationError("mission_name is required")
        object.__setattr__(self, "mission_name", self.mission_name.strip())
        validate_timestamp(self.created_at, "created_at")
        try:
            scale = float(self.meters_per_pixel)
        except (TypeError, ValueError) as error:
            raise ValidationError("meters_per_pixel must be positive") from error
        if not math.isfinite(scale) or scale <= 0:
            raise ValidationError("meters_per_pixel must be positive")
        object.__setattr__(self, "meters_per_pixel", scale)
        if not isinstance(self.robot_start, Pose):
            object.__setattr__(self, "robot_start", Pose.from_value(self.robot_start))
        entrances = tuple(
            item if isinstance(item, Entrance) else Entrance.from_value(item)
            for item in self.entrances
        )
        if not entrances:
            raise ValidationError("at least one entrance is required")
        object.__setattr__(self, "entrances", entrances)
        teams = nonnegative_int(self.available_teams, "available_teams")
        rescuers = nonnegative_int(self.available_rescuers, "available_rescuers")
        object.__setattr__(self, "available_teams", teams)
        object.__setattr__(self, "available_rescuers", rescuers)
        if self.coordinate_frame != "mission_map":
            raise ValidationError("coordinate_frame must be mission_map")
        if self.units not in {"meters", "m"}:
            raise ValidationError("units must be meters")
        object.__setattr__(self, "units", "meters")
        if not isinstance(self.source, str) or not self.source:
            raise ValidationError("source is required")
        object.__setattr__(self, "confidence", confidence(self.confidence))
        object.__setattr__(self, "coordinate_transform", copy.deepcopy(dict(self.coordinate_transform)))
        object.__setattr__(self, "extra", copy.deepcopy(dict(self.extra)))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MissionManifest":
        if not isinstance(value, Mapping):
            raise ValidationError("mission manifest must be an object")
        data = dict(value)
        base_map_value = data.get("base_map")
        if not isinstance(base_map_value, Mapping):
            base_map_value = {
                "filename": data.get("base_map_filename"),
                "sha256": data.get("base_map_sha256"),
                "width": data.get("base_map_width"),
                "height": data.get("base_map_height"),
            }
        transform = data.get("coordinate_transform", {})
        scale = data.get("meters_per_pixel")
        if scale is None and isinstance(transform, Mapping):
            scale = transform.get("meters_per_pixel")
        robot_value = data.get("robot_start", data.get("robot_start_pose"))
        robot = Pose.from_value(robot_value, "robot_start")
        if "initial_yaw" in data:
            robot = Pose(robot.x, robot.y, data["initial_yaw"])
        entrance_values = data.get("entrances", ())
        if not isinstance(entrance_values, Sequence) or isinstance(
            entrance_values, (str, bytes)
        ):
            raise ValidationError("entrances must be an array")
        known = {
            "schema_version", "mission_id", "mission_version", "artifact_version",
            "mission_name", "name", "created_at", "base_map", "base_map_filename",
            "base_map_sha256", "base_map_width", "base_map_height", "meters_per_pixel",
            "robot_start", "robot_start_pose", "initial_yaw", "entrances",
            "available_teams", "team_count", "available_rescuers",
            "rescue_personnel_count", "coordinate_frame", "coordinate_system", "units",
            "source", "confidence", "notes", "coordinate_transform",
        }
        return cls(
            schema_version=data.get("schema_version", ""),
            mission_id=data.get("mission_id"),
            mission_version=data.get("mission_version"),
            artifact_version=data.get("artifact_version", data.get("mission_version")),
            mission_name=data.get("mission_name", data.get("name")),
            created_at=data.get("created_at"),
            base_map=BaseMapInfo.from_value(base_map_value),
            meters_per_pixel=scale,
            robot_start=robot,
            entrances=tuple(Entrance.from_value(item) for item in entrance_values),
            available_teams=data.get("available_teams", data.get("team_count", 0)),
            available_rescuers=data.get(
                "available_rescuers", data.get("rescue_personnel_count", 0)
            ),
            coordinate_frame=data.get(
                "coordinate_frame",
                data.get(
                    "coordinate_system",
                    transform.get("frame_id", "mission_map") if isinstance(transform, Mapping) else "mission_map",
                ),
            ),
            units=data.get("units", "meters"),
            source=data.get("source", "host"),
            confidence=data.get("confidence", 1.0),
            notes=str(data.get("notes", "")),
            coordinate_transform=dict(transform) if isinstance(transform, Mapping) else {},
            extra={key: copy.deepcopy(item) for key, item in data.items() if key not in known},
        )

    def to_dict(self) -> dict[str, Any]:
        result = copy.deepcopy(dict(self.extra))
        result.update(
            {
                "schema_version": self.schema_version,
                "mission_id": self.mission_id,
                "mission_version": self.mission_version,
                "artifact_version": self.artifact_version,
                "mission_name": self.mission_name,
                "created_at": self.created_at,
                "base_map": self.base_map.to_dict(),
                "base_map_filename": self.base_map.filename,
                "base_map_sha256": self.base_map.sha256,
                "base_map_width": self.base_map.width,
                "base_map_height": self.base_map.height,
                "meters_per_pixel": self.meters_per_pixel,
                "robot_start": self.robot_start.to_dict(),
                "initial_yaw": self.robot_start.yaw,
                "entrances": [item.to_dict() for item in self.entrances],
                "available_teams": self.available_teams,
                "available_rescuers": self.available_rescuers,
                "coordinate_frame": self.coordinate_frame,
                "coordinate_transform": copy.deepcopy(dict(self.coordinate_transform)),
                "units": self.units,
                "source": self.source,
                "confidence": self.confidence,
                "notes": self.notes,
            }
        )
        return result


REQUIRED_SEMANTIC_ARRAYS = (
    "robot_trajectory",
    "victim_candidates",
    "confirmed_victims",
    "obstacles",
    "risk_zones",
    "explored_areas",
    "unknown_areas",
    "entry_routes",
    "team_recommendations",
    "safe_waiting_points",
)


@dataclass(frozen=True)
class SemanticResult:
    """Validated, forward-compatible Jetson result envelope."""

    data: Mapping[str, Any]

    def __post_init__(self) -> None:
        validated = self.validate(self.data)
        object.__setattr__(self, "data", validated)

    @classmethod
    def validate(
        cls, value: Mapping[str, Any], expected_mission_id: str | None = None
    ) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise ValidationError("semantic_result must be an object")
        result = copy.deepcopy(dict(value))
        if result.get("schema_version") != SCHEMA_VERSION:
            raise ValidationError("unsupported semantic_result schema_version")
        mission_id = validate_mission_id(result.get("mission_id"))
        if expected_mission_id is not None and mission_id != expected_mission_id:
            raise ValidationError("semantic_result mission_id does not match active mission")
        version = positive_int(result.get("result_version"), "result_version")
        if positive_int(result.get("artifact_version"), "artifact_version") != version:
            raise ValidationError("artifact_version must match result_version")
        positive_int(result.get("base_map_version"), "base_map_version")
        positive_int(result.get("slam_map_version"), "slam_map_version")
        validate_timestamp(result.get("created_at"), "created_at")
        confidence(result.get("confidence"), "confidence")
        if result.get("coordinate_frame") != "mission_map":
            raise ValidationError("coordinate_frame must be mission_map")
        for field_name in ("units", "source"):
            field_value = result.get(field_name)
            if not isinstance(field_value, str) or not field_value.strip():
                raise ValidationError(f"{field_name} is required")
        if result["units"] not in {"meters", "m"}:
            raise ValidationError("units must be meters")
        if not isinstance(result.get("robot_pose"), Mapping):
            raise ValidationError("robot_pose must be an object")
        Pose.from_value(result["robot_pose"], "robot_pose")
        for field_name in REQUIRED_SEMANTIC_ARRAYS:
            if not isinstance(result.get(field_name), Sequence) or isinstance(
                result.get(field_name), (str, bytes)
            ):
                raise ValidationError(f"{field_name} must be an array")
        return result

    @property
    def mission_id(self) -> str:
        return str(self.data["mission_id"])

    @property
    def result_version(self) -> int:
        return int(self.data["result_version"])

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.data))
