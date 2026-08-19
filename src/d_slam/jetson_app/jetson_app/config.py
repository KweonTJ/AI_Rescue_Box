"""Validated configuration loading with no hard-coded ROS topic dependency."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml


class ConfigurationError(ValueError):
    pass


PROTOCOL_MAX_ARTIFACT_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class TopicConfig:
    rgb: str = "/camera/color/image_raw"
    depth: str = "/camera/depth_registered/image_raw"
    camera_info: str = "/camera/depth_registered/camera_info"
    point_cloud: str = "/camera/depth/points"
    occupancy_grid: str = "/map"
    robot_pose: str = "/rtabmap/localization_pose"
    rtabmap_status: str = "/rtabmap/info"
    received_artifact: str = "/uwb/received_artifact"
    uwb_status: str = "/uwb/status"
    send_artifact: str = "/uwb/send_artifact"
    acknowledge_artifact: str = "/uwb/acknowledge_artifact"
    prior_map: str = "/ai_rescue/prior_map"
    prior_occupancy: str = "/ai_rescue/prior_occupancy"
    initial_pose: str = "/initialpose"


@dataclass(frozen=True)
class AppConfig:
    mode: str = "real"
    data_root: Path = Path("data")
    model_path: Path | None = None
    detection_confidence: float = 0.5
    map_preview_interval_seconds: float = 60.0
    map_preview_max_dimension: int = 768
    max_map_bytes: int = 10 * 1024 * 1024
    max_json_bytes: int = 2 * 1024 * 1024
    allow_unknown_routes: bool = False
    unknown_route_cost: float = 100.0
    occupied_threshold: int = 65
    minimum_passage_width_m: float = 0.8
    disconnected_minimum_cells: int = 4
    sensor_risk_cell_size_m: float = 0.25
    sensor_risk_min_points_per_cell: int = 4
    sensor_risk_debris_minimum_points: int = 12
    sensor_risk_debris_spread_m: float = 0.30
    sensor_risk_step_height_m: float = 0.18
    sensor_risk_drop_height_m: float = 0.45
    sensor_risk_depth_pixel_stride: int = 8
    sensor_risk_maximum_points: int = 40_000
    prior_map_publish_enabled: bool = True
    prior_map_dark_pixel_threshold: int = 64
    initial_pose_publish_enabled: bool = True
    topics: TopicConfig = field(default_factory=TopicConfig)

    def __post_init__(self) -> None:
        if self.mode not in {"mock", "real"}:
            raise ConfigurationError("mode must be 'mock' or 'real'")
        if not 0.0 <= self.detection_confidence <= 1.0:
            raise ConfigurationError("detection_confidence must be in [0, 1]")
        if self.map_preview_interval_seconds < 0:
            raise ConfigurationError("map preview interval cannot be negative")
        if self.map_preview_max_dimension <= 0:
            raise ConfigurationError("map preview maximum dimension must be positive")
        if self.max_map_bytes <= 0 or self.max_json_bytes <= 0:
            raise ConfigurationError("artifact limits must be positive")
        if (
            self.max_map_bytes > PROTOCOL_MAX_ARTIFACT_BYTES
            or self.max_json_bytes > PROTOCOL_MAX_ARTIFACT_BYTES
        ):
            raise ConfigurationError(
                "artifact limits cannot exceed the UWB protocol 10 MiB ceiling"
            )
        if not 0 <= self.occupied_threshold <= 100:
            raise ConfigurationError("occupied_threshold must be in [0, 100]")
        if self.minimum_passage_width_m <= 0:
            raise ConfigurationError("minimum_passage_width_m must be positive")
        if self.disconnected_minimum_cells < 1:
            raise ConfigurationError("disconnected_minimum_cells must be positive")
        if self.sensor_risk_cell_size_m <= 0:
            raise ConfigurationError("sensor_risk_cell_size_m must be positive")
        if self.sensor_risk_min_points_per_cell < 2:
            raise ConfigurationError("sensor_risk_min_points_per_cell must be at least two")
        if self.sensor_risk_debris_minimum_points < self.sensor_risk_min_points_per_cell:
            raise ConfigurationError(
                "sensor_risk_debris_minimum_points cannot be below the cell minimum"
            )
        if self.sensor_risk_debris_spread_m <= 0 or self.sensor_risk_step_height_m <= 0:
            raise ConfigurationError("sensor risk height thresholds must be positive")
        if self.sensor_risk_drop_height_m < self.sensor_risk_step_height_m:
            raise ConfigurationError(
                "sensor_risk_drop_height_m cannot be below the step threshold"
            )
        if self.sensor_risk_depth_pixel_stride < 1:
            raise ConfigurationError("sensor_risk_depth_pixel_stride must be positive")
        if self.sensor_risk_maximum_points < self.sensor_risk_min_points_per_cell:
            raise ConfigurationError("sensor_risk_maximum_points is too small")
        if not 0 <= self.prior_map_dark_pixel_threshold <= 255:
            raise ConfigurationError(
                "prior_map_dark_pixel_threshold must be in [0, 255]"
            )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "AppConfig":
        if not isinstance(value, Mapping):
            raise ConfigurationError("configuration root must be an object")
        topics_value = value.get("topics", {})
        if not isinstance(topics_value, Mapping):
            raise ConfigurationError("topics must be an object")
        allowed_topics = set(TopicConfig.__dataclass_fields__)
        unknown_topics = set(topics_value) - allowed_topics
        if unknown_topics:
            raise ConfigurationError(
                f"unknown topic configuration: {', '.join(sorted(unknown_topics))}"
            )
        topics = TopicConfig(**dict(topics_value))
        model_path = value.get("model_path")
        return cls(
            mode=str(value.get("mode", "real")),
            data_root=Path(value.get("data_root", "data")).expanduser(),
            model_path=Path(model_path).expanduser() if model_path else None,
            detection_confidence=float(value.get("detection_confidence", 0.5)),
            map_preview_interval_seconds=float(
                value.get("map_preview_interval_seconds", 60.0)
            ),
            map_preview_max_dimension=int(
                value.get("map_preview_max_dimension", 768)
            ),
            max_map_bytes=int(value.get("max_map_bytes", 10 * 1024 * 1024)),
            max_json_bytes=int(value.get("max_json_bytes", 2 * 1024 * 1024)),
            allow_unknown_routes=bool(value.get("allow_unknown_routes", False)),
            unknown_route_cost=float(value.get("unknown_route_cost", 100.0)),
            occupied_threshold=int(value.get("occupied_threshold", 65)),
            minimum_passage_width_m=float(
                value.get("minimum_passage_width_m", 0.8)
            ),
            disconnected_minimum_cells=int(
                value.get("disconnected_minimum_cells", 4)
            ),
            sensor_risk_cell_size_m=float(
                value.get("sensor_risk_cell_size_m", 0.25)
            ),
            sensor_risk_min_points_per_cell=int(
                value.get("sensor_risk_min_points_per_cell", 4)
            ),
            sensor_risk_debris_minimum_points=int(
                value.get("sensor_risk_debris_minimum_points", 12)
            ),
            sensor_risk_debris_spread_m=float(
                value.get("sensor_risk_debris_spread_m", 0.30)
            ),
            sensor_risk_step_height_m=float(
                value.get("sensor_risk_step_height_m", 0.18)
            ),
            sensor_risk_drop_height_m=float(
                value.get("sensor_risk_drop_height_m", 0.45)
            ),
            sensor_risk_depth_pixel_stride=int(
                value.get("sensor_risk_depth_pixel_stride", 8)
            ),
            sensor_risk_maximum_points=int(
                value.get("sensor_risk_maximum_points", 40_000)
            ),
            prior_map_publish_enabled=bool(
                value.get("prior_map_publish_enabled", True)
            ),
            prior_map_dark_pixel_threshold=int(
                value.get("prior_map_dark_pixel_threshold", 64)
            ),
            initial_pose_publish_enabled=bool(
                value.get("initial_pose_publish_enabled", True)
            ),
            topics=topics,
        )


def default_config_path() -> Path:
    candidates = [
        Path(__file__).resolve().parent.parent / "config" / "default.yaml",
        Path(sys.prefix) / "share" / "jetson_app" / "config" / "default.yaml",
    ]
    try:
        from ament_index_python.packages import get_package_share_directory

        candidates.insert(
            0, Path(get_package_share_directory("jetson_app")) / "config" / "default.yaml"
        )
    except (ImportError, LookupError):
        pass
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    # Keep a deterministic path in the resulting error message.
    return candidates[0]


def load_config(path: Path | None = None) -> AppConfig:
    selected = Path(
        path or os.environ.get("AI_RESCUE_JETSON_CONFIG") or default_config_path()
    )
    try:
        value = yaml.safe_load(selected.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as error:
        raise ConfigurationError(f"could not load {selected}: {error}") from error
    return AppConfig.from_mapping(value)
