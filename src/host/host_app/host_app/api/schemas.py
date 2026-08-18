"""Typed HTTP request bodies for the Host REST API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ImagePoint(StrictModel):
    x: float
    y: float


class ScaleCalibration(StrictModel):
    first: ImagePoint
    second: ImagePoint
    real_distance_m: float = Field(gt=0)


class MissionCreateRequest(StrictModel):
    map_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
    mission_name: str = Field(min_length=1, max_length=200)
    mission_id: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$"
    )
    mission_version: int = Field(default=1, ge=1)
    robot_start_image: ImagePoint
    initial_yaw: float
    entrances: list[ImagePoint] = Field(min_length=1)
    meters_per_pixel: float | None = Field(default=None, gt=0)
    scale_calibration: ScaleCalibration | None = None
    available_teams: int = Field(default=0, ge=0)
    available_rescuers: int = Field(default=0, ge=0)
    notes: str = ""

    @model_validator(mode="after")
    def validate_scale_and_resources(self) -> "MissionCreateRequest":
        if (self.meters_per_pixel is None) == (self.scale_calibration is None):
            raise ValueError(
                "provide exactly one of meters_per_pixel or scale_calibration"
            )
        if self.available_teams == 0 and self.available_rescuers == 0:
            raise ValueError("available teams or rescuers must be greater than zero")
        return self


class ReviewCommandRequest(StrictModel):
    command: Literal[
        "set_victim_status",
        "set_victim_priority",
        "set_victim_position",
        "set_route_approved",
        "modify_risk_zone",
        "clear_risk_zone",
        "add_risk_zone",
        "remove_added_risk_zone",
        "update_added_risk_zone",
        "set_team_assignments",
        "upsert_team_assignment",
        "remove_team_assignment",
        "set_safe_waiting_points",
        "add_safe_waiting_point",
        "update_safe_waiting_point",
        "remove_safe_waiting_point",
        "set_notes",
        "undo",
        "redo",
    ]
    arguments: dict[str, Any] = Field(default_factory=dict)
    expected_revision: int | None = Field(default=None, ge=0)


class PlanBuildRequest(StrictModel):
    plan_version: int = Field(ge=1)
    modified_at: str | None = None
    expected_revision: int | None = Field(default=None, ge=0)


__all__ = [
    "ImagePoint",
    "MissionCreateRequest",
    "PlanBuildRequest",
    "ReviewCommandRequest",
    "ScaleCalibration",
]
