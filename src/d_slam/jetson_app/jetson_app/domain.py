"""Typed, dependency-free domain models used by the Jetson application."""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import PurePath
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = "1.0"
MISSION_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class ValidationError(ValueError):
    """Raised when an artifact cannot safely be applied."""


class StaleVersionError(ValidationError):
    """Raised when an older or duplicate artifact would replace newer state."""


class ObservationState(str, Enum):
    OBSERVED = "observed"
    INTERPOLATED = "interpolated"
    UNKNOWN = "unknown"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_timestamp(value: str, name: str = "timestamp") -> str:
    if not isinstance(value, str) or not value:
        raise ValidationError(f"{name} must be a non-empty ISO-8601 string")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise ValidationError(f"{name} is not valid ISO-8601") from error
    if parsed.tzinfo is None:
        raise ValidationError(f"{name} must include a timezone")
    return value


def validate_confidence(value: float, name: str = "confidence") -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValidationError(f"{name} must be numeric") from error
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValidationError(f"{name} must be between 0 and 1")
    return number


def validate_mission_id(value: str) -> str:
    if not isinstance(value, str) or MISSION_ID_RE.fullmatch(value) is None:
        raise ValidationError(
            "mission_id must be 1-64 safe ASCII letters, digits, '.', '_' or '-'"
        )
    return value


def validate_safe_filename(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValidationError("base map filename must be non-empty")
    path = PurePath(value)
    if path.is_absolute() or len(path.parts) != 1 or value in {".", ".."}:
        raise ValidationError("base map filename must not contain a path")
    if path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
        raise ValidationError("base map must be JPEG or PNG")
    return value


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValidationError(f"{name} must be an integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as error:
        raise ValidationError(f"{name} must be an integer") from error
    if number < 1 or number != value:
        raise ValidationError(f"{name} must be a positive integer")
    return number


def _nonnegative_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValidationError(f"{name} must be an integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as error:
        raise ValidationError(f"{name} must be an integer") from error
    if number < 0 or number != value:
        raise ValidationError(f"{name} must be a non-negative integer")
    return number


def _finite(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValidationError(f"{name} must be numeric") from error
    if not math.isfinite(number):
        raise ValidationError(f"{name} must be finite")
    return number


@dataclass(frozen=True)
class Point2D:
    x: float
    y: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "x", _finite(self.x, "x"))
        object.__setattr__(self, "y", _finite(self.y, "y"))

    @classmethod
    def from_value(cls, value: Any, name: str = "point") -> "Point2D":
        if isinstance(value, cls):
            return value
        if isinstance(value, Mapping):
            try:
                if "x" in value and "y" in value:
                    return cls(value["x"], value["y"])
                return cls(value["map_x"], value["map_y"])
            except KeyError as error:
                raise ValidationError(f"{name} requires x/y or map_x/map_y") from error
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            if len(value) == 2:
                return cls(value[0], value[1])
        raise ValidationError(f"{name} must be an x/y object or two-item array")

    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y}


@dataclass(frozen=True)
class Pose2D(Point2D):
    yaw: float = 0.0

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "yaw", _finite(self.yaw, "yaw"))

    @classmethod
    def from_value(cls, value: Any, name: str = "pose") -> "Pose2D":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise ValidationError(f"{name} must be an object")
        try:
            if "x" in value and "y" in value:
                return cls(value["x"], value["y"], value.get("yaw", 0.0))
            return cls(value["map_x"], value["map_y"], value.get("yaw", 0.0))
        except KeyError as error:
            raise ValidationError(f"{name} requires x/y or map_x/map_y") from error

    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "yaw": self.yaw}


@dataclass(frozen=True)
class BoundingBox:
    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        for name in ("x", "y", "width", "height"):
            object.__setattr__(self, name, _finite(getattr(self, name), name))
        if self.width <= 0 or self.height <= 0:
            raise ValidationError("bounding box dimensions must be positive")

    @classmethod
    def from_value(cls, value: Any) -> "BoundingBox":
        if isinstance(value, cls):
            return value
        if isinstance(value, Mapping):
            if {"x", "y", "width", "height"} <= set(value):
                return cls(value["x"], value["y"], value["width"], value["height"])
            if {"x1", "y1", "x2", "y2"} <= set(value):
                return cls(
                    value["x1"],
                    value["y1"],
                    float(value["x2"]) - float(value["x1"]),
                    float(value["y2"]) - float(value["y1"]),
                )
        if isinstance(value, Sequence) and len(value) == 4:
            return cls(*value)
        raise ValidationError("bounding box must have x, y, width and height")

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(frozen=True)
class CameraPoint:
    x: float
    y: float
    z: float

    def __post_init__(self) -> None:
        for name in ("x", "y", "z"):
            object.__setattr__(self, name, _finite(getattr(self, name), name))

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass
class PersonCandidate:
    detection_id: str
    tracking_id: str | None
    class_name: str
    bbox: BoundingBox
    confidence: float
    depth_valid: bool
    camera_position: CameraPoint | None
    map_position: Point2D | None
    detected_at: str
    source: str
    host_status: str = "candidate"
    observation_count: int = 1
    last_seen_at: str | None = None

    def __post_init__(self) -> None:
        if not self.detection_id:
            raise ValidationError("detection_id is required")
        self.confidence = validate_confidence(self.confidence)
        validate_timestamp(self.detected_at, "detected_at")
        if self.last_seen_at is None:
            self.last_seen_at = self.detected_at
        else:
            validate_timestamp(self.last_seen_at, "last_seen_at")
        if self.depth_valid != (self.camera_position is not None):
            raise ValidationError("depth_valid must match camera_position availability")
        if self.observation_count < 1:
            raise ValidationError("observation_count must be positive")

    def to_dict(self) -> dict[str, Any]:
        map_position = self.map_position.to_dict() if self.map_position else None
        return {
            "detection_id": self.detection_id,
            "tracking_id": self.tracking_id,
            "class": self.class_name,
            "rgb_bbox": self.bbox.to_dict(),
            "confidence": self.confidence,
            "depth_valid": self.depth_valid,
            "camera_position": (
                self.camera_position.to_dict() if self.camera_position else None
            ),
            "map_position": map_position,
            "position": map_position,
            "detected_at": self.detected_at,
            "last_seen_at": self.last_seen_at,
            "source": self.source,
            "host_status": self.host_status,
            "observation_count": self.observation_count,
        }


@dataclass(frozen=True)
class RiskZone:
    risk_id: str
    risk_type: str
    polygon: tuple[Point2D, ...]
    severity: float
    confidence: float
    rationale: str
    source: str
    observed_at: str
    state: ObservationState
    host_status: str = "candidate"

    def __post_init__(self) -> None:
        if not self.risk_id or not self.risk_type:
            raise ValidationError("risk_id and risk_type are required")
        if len(self.polygon) < 1:
            raise ValidationError("a risk zone needs at least one point")
        object.__setattr__(self, "severity", validate_confidence(self.severity, "severity"))
        object.__setattr__(self, "confidence", validate_confidence(self.confidence))
        validate_timestamp(self.observed_at, "observed_at")
        if not isinstance(self.state, ObservationState):
            object.__setattr__(self, "state", ObservationState(self.state))

    @property
    def center(self) -> Point2D:
        return Point2D(
            sum(point.x for point in self.polygon) / len(self.polygon),
            sum(point.y for point in self.polygon) / len(self.polygon),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_id": self.risk_id,
            "risk_type": self.risk_type,
            "polygon": [point.to_dict() for point in self.polygon],
            "center": self.center.to_dict(),
            "severity": self.severity,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "source": self.source,
            "observed_at": self.observed_at,
            "state": self.state.value,
            "host_status": self.host_status,
        }


@dataclass(frozen=True)
class OccupancyGrid:
    width: int
    height: int
    resolution: float
    origin: Point2D
    data: tuple[int, ...]
    frame_id: str = "map"

    def __post_init__(self) -> None:
        object.__setattr__(self, "width", _positive_int(self.width, "grid width"))
        object.__setattr__(self, "height", _positive_int(self.height, "grid height"))
        resolution = _finite(self.resolution, "grid resolution")
        if resolution <= 0:
            raise ValidationError("grid resolution must be positive")
        object.__setattr__(self, "resolution", resolution)
        if len(self.data) != self.width * self.height:
            raise ValidationError("occupancy data length does not match grid dimensions")
        if any(value < -1 or value > 100 for value in self.data):
            raise ValidationError("occupancy values must be between -1 and 100")

    def index(self, x: int, y: int) -> int:
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise IndexError((x, y))
        return y * self.width + x

    def value(self, x: int, y: int) -> int:
        return self.data[self.index(x, y)]

    def cell_to_world(self, cell: tuple[int, int]) -> Point2D:
        x, y = cell
        self.index(x, y)
        return Point2D(
            self.origin.x + (x + 0.5) * self.resolution,
            self.origin.y + (y + 0.5) * self.resolution,
        )

    def world_to_cell(self, point: Point2D) -> tuple[int, int]:
        x = math.floor((point.x - self.origin.x) / self.resolution)
        y = math.floor((point.y - self.origin.y) / self.resolution)
        self.index(x, y)
        return x, y


@dataclass(frozen=True)
class RoutePlan:
    route_id: str
    start: Point2D
    goal: Point2D
    points: tuple[Point2D, ...]
    total_distance: float
    risk_cost: float
    contains_unknown: bool
    created_at: str
    map_version: int
    target_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "route_id": self.route_id,
            "start": self.start.to_dict(),
            "goal": self.goal.to_dict(),
            "points": [point.to_dict() for point in self.points],
            "total_distance": self.total_distance,
            "risk_cost": self.risk_cost,
            "contains_unknown": self.contains_unknown,
            "created_at": self.created_at,
            "map_version": self.map_version,
            "target_id": self.target_id,
        }


@dataclass(frozen=True)
class TeamRecommendation:
    team_id: str
    position: Point2D
    victim_id: str | None
    route_id: str | None
    estimated_distance: float
    risk_cost: float
    rationale: str
    confidence: float
    host_status: str = "pending"

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["position"] = self.position.to_dict()
        return result


@dataclass(frozen=True)
class MissionManifest:
    schema_version: str
    mission_id: str
    mission_version: int
    artifact_version: int
    mission_name: str
    created_at: str
    base_map_filename: str
    base_map_sha256: str
    base_map_width: int
    base_map_height: int
    meters_per_pixel: float
    robot_start: Pose2D
    entrances: tuple[Point2D, ...]
    available_teams: int
    available_rescuers: int
    coordinate_frame: str
    units: str
    source: str
    confidence: float
    notes: str = ""
    coordinate_transform: Mapping[str, Any] = field(default_factory=dict)
    robot_start_details: Mapping[str, Any] = field(default_factory=dict)
    entrance_details: tuple[Mapping[str, Any], ...] = ()
    extra: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MissionManifest":
        if not isinstance(value, Mapping):
            raise ValidationError("mission manifest must be a JSON object")
        data = dict(value)
        schema_version = str(data.get("schema_version", ""))
        if schema_version != SCHEMA_VERSION:
            raise ValidationError(
                f"unsupported schema_version {schema_version!r}; expected {SCHEMA_VERSION}"
            )
        mission_id = validate_mission_id(data.get("mission_id"))
        mission_version = _positive_int(data.get("mission_version"), "mission_version")
        artifact_version = _positive_int(
            data.get("artifact_version", mission_version), "artifact_version"
        )
        if artifact_version != mission_version:
            raise ValidationError("artifact_version must match mission_version")
        mission_name = data.get("mission_name") or data.get("name")
        if not isinstance(mission_name, str) or not mission_name.strip():
            raise ValidationError("mission_name is required")
        created_at = validate_timestamp(data.get("created_at"), "created_at")

        map_info = data.get("base_map") if isinstance(data.get("base_map"), Mapping) else {}
        filename = data.get("base_map_filename") or map_info.get("filename")
        sha256 = data.get("base_map_sha256") or map_info.get("sha256")
        size = data.get("base_map_size") or data.get("image_size") or {}
        width = data.get("base_map_width") or map_info.get("width") or size.get("width")
        height = data.get("base_map_height") or map_info.get("height") or size.get("height")
        filename = validate_safe_filename(filename)
        if not isinstance(sha256, str) or SHA256_RE.fullmatch(sha256) is None:
            raise ValidationError("base_map_sha256 must be 64 lowercase hex characters")

        transform = (
            data.get("coordinate_transform")
            if isinstance(data.get("coordinate_transform"), Mapping)
            else {}
        )
        top_scale = data.get("meters_per_pixel")
        transform_scale = transform.get("meters_per_pixel")
        if top_scale is not None and transform_scale is not None:
            if not math.isclose(
                _finite(top_scale, "meters_per_pixel"),
                _finite(transform_scale, "coordinate_transform.meters_per_pixel"),
                rel_tol=0.0,
                abs_tol=1e-12,
            ):
                raise ValidationError("conflicting meters_per_pixel values")
        scale = top_scale if top_scale is not None else transform_scale
        scale = _finite(scale, "meters_per_pixel")
        if scale <= 0:
            raise ValidationError("meters_per_pixel must be positive")
        robot_data = data.get("robot_start") or data.get("robot_start_pose")
        robot_start = Pose2D.from_value(robot_data, "robot_start")
        if "initial_yaw" in data:
            initial_yaw = _finite(data["initial_yaw"], "initial_yaw")
            if not math.isclose(robot_start.yaw, initial_yaw, rel_tol=0.0, abs_tol=1e-12):
                raise ValidationError("initial_yaw conflicts with robot_start.yaw")

        entrances_value = data.get("entrances", [])
        if not isinstance(entrances_value, Sequence) or isinstance(entrances_value, (str, bytes)):
            raise ValidationError("entrances must be an array")
        entrances = tuple(Point2D.from_value(item, "entrance") for item in entrances_value)
        if not entrances:
            raise ValidationError("at least one entrance is required")

        available_teams = _nonnegative_int(data.get("available_teams", data.get("team_count", 0)), "available_teams")
        available_rescuers = _nonnegative_int(data.get("available_rescuers", data.get("rescue_personnel_count", 0)), "available_rescuers")

        frame = data.get("coordinate_frame") or data.get("coordinate_system") or transform.get("frame_id") or "mission_map"
        if frame != "mission_map":
            raise ValidationError("coordinate_frame must be mission_map")
        transform_frame = transform.get("frame_id")
        if transform_frame is not None and transform_frame != frame:
            raise ValidationError("coordinate frame conflicts with transform frame_id")
        units = data.get("units", "meters")
        if units not in {"meters", "m"}:
            raise ValidationError("units must be meters")
        source = data.get("source", "host")
        if not isinstance(source, str) or not source:
            raise ValidationError("source is required")
        confidence = validate_confidence(data.get("confidence", 1.0))

        known = {
            "schema_version", "mission_id", "mission_version", "artifact_version",
            "mission_name", "name", "created_at", "base_map", "base_map_filename",
            "base_map_sha256", "base_map_width", "base_map_height", "base_map_size",
            "image_size", "meters_per_pixel", "robot_start", "robot_start_pose",
            "initial_yaw", "entrances", "available_teams", "team_count",
            "available_rescuers", "rescue_personnel_count", "coordinate_frame",
            "coordinate_system", "units", "source", "confidence", "notes",
            "coordinate_transform",
        }
        return cls(
            schema_version=schema_version,
            mission_id=mission_id,
            mission_version=mission_version,
            artifact_version=artifact_version,
            mission_name=mission_name.strip(),
            created_at=created_at,
            base_map_filename=filename,
            base_map_sha256=sha256,
            base_map_width=_positive_int(width, "base_map_width"),
            base_map_height=_positive_int(height, "base_map_height"),
            meters_per_pixel=scale,
            robot_start=robot_start,
            entrances=entrances,
            available_teams=available_teams,
            available_rescuers=available_rescuers,
            coordinate_frame=frame,
            units="meters",
            source=source,
            confidence=confidence,
            notes=str(data.get("notes", "")),
            coordinate_transform=dict(transform),
            robot_start_details=dict(robot_data),
            entrance_details=tuple(dict(item) if isinstance(item, Mapping) else {} for item in entrances_value),
            extra={key: item for key, item in data.items() if key not in known},
        )

    def to_dict(self) -> dict[str, Any]:
        result = dict(self.extra)
        robot_start = dict(self.robot_start_details)
        robot_start.update({"x": self.robot_start.x, "y": self.robot_start.y, "map_x": self.robot_start.x, "map_y": self.robot_start.y, "yaw": self.robot_start.yaw})
        entrances = []
        for index, point in enumerate(self.entrances):
            details = dict(self.entrance_details[index]) if index < len(self.entrance_details) else {}
            details.update({"x": point.x, "y": point.y, "map_x": point.x, "map_y": point.y})
            entrances.append(details)
        result.update({
            "schema_version": self.schema_version,
            "mission_id": self.mission_id,
            "mission_version": self.mission_version,
            "artifact_version": self.artifact_version,
            "mission_name": self.mission_name,
            "created_at": self.created_at,
            "base_map": {"filename": self.base_map_filename, "sha256": self.base_map_sha256, "width": self.base_map_width, "height": self.base_map_height},
            "base_map_filename": self.base_map_filename,
            "base_map_sha256": self.base_map_sha256,
            "base_map_width": self.base_map_width,
            "base_map_height": self.base_map_height,
            "meters_per_pixel": self.meters_per_pixel,
            "robot_start": robot_start,
            "initial_yaw": self.robot_start.yaw,
            "entrances": entrances,
            "available_teams": self.available_teams,
            "available_rescuers": self.available_rescuers,
            "coordinate_frame": self.coordinate_frame,
            "units": self.units,
            "source": self.source,
            "confidence": self.confidence,
            "notes": self.notes,
            "coordinate_transform": dict(self.coordinate_transform),
        })
        return result


@dataclass(frozen=True)
class SemanticResult:
    mission_id: str
    base_map_version: int
    result_version: int
    coordinate_frame: str
    robot_pose: Pose2D
    trajectory: tuple[Pose2D, ...]
    victim_candidates: tuple[PersonCandidate, ...]
    risks: tuple[RiskZone, ...]
    routes: tuple[RoutePlan, ...]
    recommendations: tuple[TeamRecommendation, ...]
    slam_map_version: int
    obstacles: tuple[tuple[Point2D, ...], ...] = ()
    explored_areas: tuple[tuple[Point2D, ...], ...] = ()
    unknown_areas: tuple[tuple[Point2D, ...], ...] = ()
    confirmed_victims: tuple[PersonCandidate, ...] = ()
    safe_waiting_points: tuple[Point2D, ...] = ()
    map_alignment: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION
    created_at: str = field(default_factory=utc_now)
    units: str = "meters"
    source: str = "jetson_sensor_analysis"
    confidence: float = 0.0
    analysis_mode: str = "real"

    def __post_init__(self) -> None:
        validate_mission_id(self.mission_id)
        _positive_int(self.base_map_version, "base_map_version")
        _positive_int(self.result_version, "result_version")
        _positive_int(self.slam_map_version, "slam_map_version")
        validate_timestamp(self.created_at, "created_at")
        validate_confidence(self.confidence)
        if self.schema_version != SCHEMA_VERSION:
            raise ValidationError("unsupported semantic result schema version")
        if self.coordinate_frame != "mission_map":
            raise ValidationError("coordinate_frame must be mission_map")
        if self.units not in {"meters", "m"}:
            raise ValidationError("units must be meters")
        if self.analysis_mode not in {"real", "mock"}:
            raise ValidationError("analysis_mode must be real or mock")
        if not isinstance(self.source, str) or not self.source:
            raise ValidationError("semantic result source is required")
        source_is_mock = "mock" in self.source.lower()
        if source_is_mock != (self.analysis_mode == "mock"):
            raise ValidationError("semantic result source must clearly agree with analysis_mode")
        if not isinstance(self.map_alignment, Mapping):
            raise ValidationError("map_alignment must be an object")
        object.__setattr__(self, "map_alignment", dict(self.map_alignment))

    def to_dict(self) -> dict[str, Any]:
        polygons = lambda values: [[point.to_dict() for point in polygon] for polygon in values]
        return {
            "schema_version": self.schema_version,
            "mission_id": self.mission_id,
            "artifact_version": self.result_version,
            "base_map_version": self.base_map_version,
            "result_version": self.result_version,
            "created_at": self.created_at,
            "coordinate_frame": self.coordinate_frame,
            "units": "meters",
            "source": self.source,
            "analysis_mode": self.analysis_mode,
            "confidence": self.confidence,
            "robot_pose": self.robot_pose.to_dict(),
            "robot_trajectory": [pose.to_dict() for pose in self.trajectory],
            "victim_candidates": [item.to_dict() for item in self.victim_candidates],
            "confirmed_victims": [item.to_dict() for item in self.confirmed_victims],
            "obstacles": polygons(self.obstacles),
            "risk_zones": [item.to_dict() for item in self.risks],
            "explored_areas": polygons(self.explored_areas),
            "unknown_areas": polygons(self.unknown_areas),
            "entry_routes": [item.to_dict() for item in self.routes],
            "team_recommendations": [item.to_dict() for item in self.recommendations],
            "safe_waiting_points": [point.to_dict() for point in self.safe_waiting_points],
            "slam_map_version": self.slam_map_version,
            "map_alignment": dict(self.map_alignment),
        }


def mean_confidence(values: Iterable[float], default: float = 0.0) -> float:
    items = [validate_confidence(item) for item in values]
    return sum(items) / len(items) if items else default
