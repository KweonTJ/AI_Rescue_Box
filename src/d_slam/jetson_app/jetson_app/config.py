"""Validated Jetson application configuration."""
from __future__ import annotations
from dataclasses import dataclass,field
from pathlib import Path
from typing import Any,Mapping
import os,yaml
class ConfigurationError(ValueError): pass
PROTOCOL_MAX_ARTIFACT_BYTES=10*1024*1024
@dataclass(frozen=True)
class TopicConfig:
    rgb:str="/camera/color/image_raw"; depth:str="/camera/depth_registered/image_raw"; camera_info:str="/camera/depth_registered/camera_info"; point_cloud:str="/camera/depth/points"; occupancy_grid:str="/map"; robot_pose:str="/rtabmap/localization_pose"; rtabmap_status:str="/rtabmap/info"; prior_map:str="/ai_rescue/prior_map"; prior_occupancy:str="/ai_rescue/prior_occupancy"; initial_pose:str="/initialpose"
@dataclass(frozen=True)
class AppConfig:
    mode:str="real"; data_root:Path=Path("data"); model_path:Path|None=None; detection_confidence:float=.5; map_preview_interval_seconds:float=60.; map_preview_max_dimension:int=768; max_map_bytes:int=10*1024*1024; max_json_bytes:int=2*1024*1024; allow_unknown_routes:bool=False; unknown_route_cost:float=100.; occupied_threshold:int=65; minimum_passage_width_m:float=.8; disconnected_minimum_cells:int=4; topics:TopicConfig=field(default_factory=TopicConfig)
    def __post_init__(self):
        if self.mode not in {"mock","real"}: raise ConfigurationError("mode must be 'mock' or 'real'")
        if not 0<=self.detection_confidence<=1: raise ConfigurationError("detection_confidence must be in [0, 1]")
        if self.map_preview_interval_seconds<0 or self.map_preview_max_dimension<=0: raise ConfigurationError("invalid map preview configuration")
        if self.max_map_bytes<=0 or self.max_json_bytes<=0 or self.max_map_bytes>PROTOCOL_MAX_ARTIFACT_BYTES or self.max_json_bytes>PROTOCOL_MAX_ARTIFACT_BYTES: raise ConfigurationError("invalid artifact limits")
        if not 0<=self.occupied_threshold<=100 or self.minimum_passage_width_m<=0: raise ConfigurationError("invalid map thresholds")
    @classmethod
    def from_mapping(cls,value:Mapping[str,Any])->"AppConfig":
        if not isinstance(value,Mapping): raise ConfigurationError("configuration root must be an object")
        topics_value=value.get("topics",{}); allowed=set(TopicConfig.__dataclass_fields__); unknown=set(topics_value)-allowed
        if unknown: raise ConfigurationError(f"unknown topic configuration: {', '.join(sorted(unknown))}")
        topics=TopicConfig(**dict(topics_value)); model_path=value.get("model_path")
        return cls(mode=str(value.get("mode","real")),data_root=Path(value.get("data_root","data")).expanduser(),model_path=Path(model_path).expanduser() if model_path else None,detection_confidence=float(value.get("detection_confidence",.5)),map_preview_interval_seconds=float(value.get("map_preview_interval_seconds",60)),map_preview_max_dimension=int(value.get("map_preview_max_dimension",768)),max_map_bytes=int(value.get("max_map_bytes",10*1024*1024)),max_json_bytes=int(value.get("max_json_bytes",2*1024*1024)),allow_unknown_routes=bool(value.get("allow_unknown_routes",False)),unknown_route_cost=float(value.get("unknown_route_cost",100)),occupied_threshold=int(value.get("occupied_threshold",65)),minimum_passage_width_m=float(value.get("minimum_passage_width_m",.8)),disconnected_minimum_cells=int(value.get("disconnected_minimum_cells",4)),topics=topics)
def load_config(path:Path|None=None)->AppConfig:
    selected=Path(path or os.environ.get("AI_RESCUE_JETSON_CONFIG") or Path(__file__).resolve().parent.parent/"config"/"default.yaml")
    try: value=yaml.safe_load(selected.read_text(encoding="utf-8")) or {}
    except (OSError,yaml.YAMLError) as error: raise ConfigurationError(f"could not load {selected}: {error}") from error
    return AppConfig.from_mapping(value)
