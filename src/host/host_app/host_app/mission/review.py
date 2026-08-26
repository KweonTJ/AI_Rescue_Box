"""Non-destructive review overlay with bounded undo/redo history."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ..errors import ValidationError
from ..map_editor.coordinates import Point
from .models import (
    SCHEMA_VERSION,
    SemanticResult,
    confidence,
    positive_int,
    utc_now,
    validate_mission_id,
    validate_timestamp,
)


SENSOR_LAYER_KEYS = (
    "robot_pose",
    "robot_trajectory",
    "victim_candidates",
    "confirmed_victims",
    "obstacles",
    "risk_zones",
    "explored_areas",
    "unknown_areas",
)
RECOMMENDATION_LAYER_KEYS = (
    "entry_routes",
    "team_recommendations",
    "safe_waiting_points",
)


def _array(value: Any, name: str) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValidationError(f"{name} must be an array")
    return copy.deepcopy(list(value))


@dataclass(frozen=True)
class ApprovedPlan:
    mission_id: str
    mission_version: int
    base_result_version: int
    approved_plan_version: int
    modified_at: str
    coordinate_frame: str = "mission_map"
    approved_victims: tuple[Mapping[str, Any], ...] = ()
    excluded_victim_candidates: tuple[Mapping[str, Any], ...] = ()
    approved_risk_zones: tuple[Mapping[str, Any], ...] = ()
    modified_or_cleared_risk_zones: tuple[Mapping[str, Any], ...] = ()
    final_team_assignments: tuple[Mapping[str, Any], ...] = ()
    approved_routes: tuple[Mapping[str, Any], ...] = ()
    priorities: tuple[Mapping[str, Any], ...] = ()
    safe_waiting_points: tuple[Mapping[str, Any], ...] = ()
    notes: str = ""
    source: str = "host_approved"
    confidence: float = 1.0
    schema_version: str = SCHEMA_VERSION
    artifact_version: int | None = None
    units: str = "meters"
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValidationError("unsupported approved_plan schema_version")
        object.__setattr__(self, "mission_id", validate_mission_id(self.mission_id))
        mission_version = positive_int(self.mission_version, "mission_version")
        object.__setattr__(self, "mission_version", mission_version)
        result_version = positive_int(self.base_result_version, "base_result_version")
        plan_version = positive_int(self.approved_plan_version, "approved_plan_version")
        object.__setattr__(self, "base_result_version", result_version)
        object.__setattr__(self, "approved_plan_version", plan_version)
        artifact_version = plan_version if self.artifact_version is None else self.artifact_version
        if positive_int(artifact_version, "artifact_version") != plan_version:
            raise ValidationError("artifact_version must match approved_plan_version")
        object.__setattr__(self, "artifact_version", plan_version)
        validate_timestamp(self.modified_at, "modified_at")
        if not isinstance(self.coordinate_frame, str) or not self.coordinate_frame.strip():
            raise ValidationError("coordinate_frame is required")
        if self.units not in {"meters", "m"}:
            raise ValidationError("units must be meters")
        object.__setattr__(self, "units", "meters")
        if not isinstance(self.source, str) or not self.source:
            raise ValidationError("source is required")
        object.__setattr__(self, "confidence", confidence(self.confidence))
        for field_name in (
            "approved_victims",
            "excluded_victim_candidates",
            "approved_risk_zones",
            "modified_or_cleared_risk_zones",
            "final_team_assignments",
            "approved_routes",
            "priorities",
            "safe_waiting_points",
        ):
            items = getattr(self, field_name)
            object.__setattr__(
                self, field_name, tuple(copy.deepcopy(dict(item)) for item in items)
            )
        object.__setattr__(self, "extra", copy.deepcopy(dict(self.extra)))

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        expected_mission_id: str | None = None,
        expected_mission_version: int | None = None,
        expected_result_version: int | None = None,
    ) -> "ApprovedPlan":
        if not isinstance(value, Mapping):
            raise ValidationError("approved_plan must be an object")
        data = dict(value)
        mission_id = data.get("mission_id")
        if expected_mission_id is not None and mission_id != expected_mission_id:
            raise ValidationError("approved_plan mission_id does not match active mission")
        mission_version = data.get("mission_version", data.get("base_map_version"))
        if (
            expected_mission_version is not None
            and mission_version != expected_mission_version
        ):
            raise ValidationError("approved_plan mission_version does not match active mission")
        base_result_version = data.get(
            "base_result_version",
            data.get("semantic_result_version", data.get("based_on_result_version")),
        )
        if (
            expected_result_version is not None
            and base_result_version != expected_result_version
        ):
            raise ValidationError("approved_plan is based on a stale semantic result")
        plan_version = data.get("approved_plan_version", data.get("plan_version"))
        known = {
            "schema_version", "mission_id", "mission_version", "base_map_version",
            "base_result_version", "semantic_result_version", "based_on_result_version",
            "approved_plan_version", "plan_version", "artifact_version", "modified_at",
            "updated_at", "approved_victims", "excluded_victim_candidates",
            "approved_risk_zones", "modified_or_cleared_risk_zones",
            "final_team_assignments", "approved_routes", "priorities",
            "safe_waiting_points", "notes", "coordinate_frame", "source", "confidence", "units",
        }
        arrays = {}
        for name in (
            "approved_victims", "excluded_victim_candidates", "approved_risk_zones",
            "modified_or_cleared_risk_zones", "final_team_assignments",
            "approved_routes", "priorities", "safe_waiting_points",
        ):
            arrays[name] = tuple(_array(data.get(name, []), name))
        return cls(
            schema_version=data.get("schema_version", ""),
            mission_id=mission_id,
            mission_version=mission_version,
            base_result_version=base_result_version,
            approved_plan_version=plan_version,
            artifact_version=data.get("artifact_version", plan_version),
            modified_at=data.get("modified_at", data.get("updated_at")),
            coordinate_frame=data.get("coordinate_frame", "map"),
            notes=str(data.get("notes", "")),
            source=data.get("source", "host_approved"),
            confidence=data.get("confidence", 1.0),
            units=data.get("units", "meters"),
            extra={key: copy.deepcopy(item) for key, item in data.items() if key not in known},
            **arrays,
        )

    def to_dict(self) -> dict[str, Any]:
        result = copy.deepcopy(dict(self.extra))
        result.update(
            {
                "schema_version": self.schema_version,
                "mission_id": self.mission_id,
                "mission_version": self.mission_version,
                "base_result_version": self.base_result_version,
                "semantic_result_version": self.base_result_version,
                "approved_plan_version": self.approved_plan_version,
                "artifact_version": self.artifact_version,
                "modified_at": self.modified_at,
                "coordinate_frame": self.coordinate_frame,
                "approved_victims": copy.deepcopy(list(self.approved_victims)),
                "excluded_victim_candidates": copy.deepcopy(
                    list(self.excluded_victim_candidates)
                ),
                "approved_risk_zones": copy.deepcopy(list(self.approved_risk_zones)),
                "modified_or_cleared_risk_zones": copy.deepcopy(
                    list(self.modified_or_cleared_risk_zones)
                ),
                "final_team_assignments": copy.deepcopy(list(self.final_team_assignments)),
                "approved_routes": copy.deepcopy(list(self.approved_routes)),
                "priorities": copy.deepcopy(list(self.priorities)),
                "safe_waiting_points": copy.deepcopy(list(self.safe_waiting_points)),
                "notes": self.notes,
                "source": self.source,
                "confidence": self.confidence,
                "units": self.units,
            }
        )
        return result


def _identifier(item: Mapping[str, Any], candidates: tuple[str, ...]) -> str | None:
    for key in candidates:
        value = item.get(key)
        if value is not None:
            return str(value)
    return None


def _point_dict(x: Any, y: Any) -> dict[str, float]:
    point = Point(x, y)
    return {"x": point.x, "y": point.y}


def _validate_risk_zone(value: Mapping[str, Any], *, risk_id: str | None = None) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValidationError("risk_zone must be an object")
    result = copy.deepcopy(dict(value))
    identifier = str(result.get("risk_id", risk_id or "")).strip()
    if not identifier:
        raise ValidationError("risk zone requires risk_id")
    result["risk_id"] = identifier
    risk_type = str(result.get("risk_type", "")).strip()
    if not risk_type:
        raise ValidationError("risk zone requires risk_type")
    result["risk_type"] = risk_type
    state = result.get("state", "unknown")
    if state not in {"observed", "interpolated", "unknown"}:
        raise ValidationError("risk state must be observed, interpolated, or unknown")
    polygon = result.get("polygon")
    if not isinstance(polygon, Sequence) or isinstance(polygon, (str, bytes)) or not polygon:
        raise ValidationError("risk zone requires at least one polygon point")
    points = [Point.from_value(item, "risk polygon point") for item in polygon]
    result["polygon"] = [_point_dict(point.x, point.y) for point in points]
    result["severity"] = confidence(result.get("severity", 0.5), "severity")
    result["confidence"] = confidence(result.get("confidence", 1.0), "confidence")
    result.setdefault("source", "host_user")
    result["host_status"] = "modified" if risk_id else "added"
    return result


def _validate_assignment(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValidationError("team assignment must be an object")
    result = copy.deepcopy(dict(value))
    team_id = str(result.get("team_id", "")).strip()
    if not team_id:
        raise ValidationError("team assignment requires team_id")
    result["team_id"] = team_id
    position = (
        result.get("position")
        or result.get("current_position")
        or result.get("recommended_position")
        or result.get("map_position")
    )
    if not isinstance(position, Mapping):
        raise ValidationError("team assignment requires position")
    result["position"] = _point_dict(position.get("x"), position.get("y"))
    victim_id = result.get("victim_id", result.get("assigned_victim_id"))
    result["victim_id"] = None if victim_id in {None, ""} else str(victim_id)
    route_id = result.get("route_id")
    result["route_id"] = None if route_id in {None, ""} else str(route_id)
    result["host_status"] = "modified"
    result.setdefault("source", "host_user")
    return result


def _waiting_id(item: Mapping[str, Any], index: int | None = None) -> str:
    identifier = _identifier(item, ("waiting_id", "safe_waiting_id", "id"))
    if identifier:
        return identifier
    if index is None:
        raise ValidationError("safe waiting point requires waiting_id")
    return f"jetson-wait-{index + 1}"


class ReviewSession:
    """Keep Jetson data immutable and record Host edits as a separate overlay."""

    def __init__(self, result: SemanticResult | Mapping[str, Any], history_limit: int = 100):
        if history_limit < 1:
            raise ValidationError("history_limit must be positive")
        semantic = result if isinstance(result, SemanticResult) else SemanticResult(result)
        self._original = semantic.to_dict()
        self._sensor = {
            key: copy.deepcopy(self._original[key]) for key in SENSOR_LAYER_KEYS
        }
        self._recommendations = {
            key: copy.deepcopy(self._original[key]) for key in RECOMMENDATION_LAYER_KEYS
        }
        self._edits: dict[str, Any] = {
            "victim_status": {},
            "victim_priorities": {},
            "victim_modifications": {},
            "added_victims": [],
            "risk_modifications": {},
            "cleared_risk_ids": [],
            "added_risk_zones": [],
            "route_approvals": {},
            "team_assignments": None,
            "safe_waiting_points": [],
            "notes": "",
        }
        for index, value in enumerate(self._original.get("safe_waiting_points", [])):
            point = Point.from_value(value, "safe waiting point")
            details = copy.deepcopy(dict(value))
            details.update(
                {
                    "waiting_id": _waiting_id(details, index),
                    "x": point.x,
                    "y": point.y,
                    "source": details.get("source", "jetson_recommendation"),
                    "host_status": "unchanged",
                }
            )
            self._edits["safe_waiting_points"].append(details)
        self._history_limit = history_limit
        self._undo: list[dict[str, Any]] = []
        self._redo: list[dict[str, Any]] = []
        self._final_approved: dict[str, Any] | None = None

    @property
    def original_result(self) -> dict[str, Any]:
        return copy.deepcopy(self._original)

    @property
    def sensor_analysis(self) -> dict[str, Any]:
        return copy.deepcopy(self._sensor)

    @property
    def recommendations(self) -> dict[str, Any]:
        return copy.deepcopy(self._recommendations)

    @property
    def host_edits(self) -> dict[str, Any]:
        return copy.deepcopy(self._edits)

    @property
    def final_approved(self) -> dict[str, Any] | None:
        return copy.deepcopy(self._final_approved)

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def _before_edit(self) -> None:
        self._undo.append(copy.deepcopy(self._edits))
        if len(self._undo) > self._history_limit:
            del self._undo[0]
        self._redo.clear()
        self._final_approved = None

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(copy.deepcopy(self._edits))
        self._edits = self._undo.pop()
        self._final_approved = None
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(copy.deepcopy(self._edits))
        self._edits = self._redo.pop()
        self._final_approved = None
        return True

    def set_victim_status(self, victim_id: str, status: str) -> None:
        if status not in {"pending", "confirmed", "excluded"}:
            raise ValidationError("victim status must be pending, confirmed, or excluded")
        self._before_edit()
        self._edits["victim_status"][str(victim_id)] = status

    def set_victim_priority(self, victim_id: str, priority: int) -> None:
        self._before_edit()
        self._edits["victim_priorities"][str(victim_id)] = positive_int(
            priority, "priority"
        )

    def set_victim_position(self, victim_id: str, x: float, y: float) -> None:
        victim_id = str(victim_id)
        point = _point_dict(x, y)
        known_ids = {
            _identifier(item, ("detection_id", "victim_id", "id"))
            for item in self._original["victim_candidates"] + self._original["confirmed_victims"]
        }
        if victim_id in known_ids:
            self._before_edit()
            self._edits["victim_modifications"].setdefault(victim_id, {}).update(
                {
                    "x": point["x"],
                    "y": point["y"],
                    "map_position": point,
                    "position": point,
                    "host_status": "position_modified",
                }
            )
            return

        added = copy.deepcopy(self._edits["added_victims"])
        for item in added:
            if _identifier(item, ("detection_id", "victim_id", "id")) == victim_id:
                self._before_edit()
                item.update(
                    {
                        "x": point["x"],
                        "y": point["y"],
                        "map_position": point,
                        "position": point,
                        "host_status": "modified",
                    }
                )
                self._edits["added_victims"] = added
                return
        raise ValidationError("victim marker was not found")

    def add_victim(self, victim_id: str, x: float, y: float) -> None:
        victim_id = str(victim_id).strip()
        if not victim_id:
            raise ValidationError("victim_id is required")
        all_ids = {
            _identifier(item, ("detection_id", "victim_id", "id"))
            for item in self._original["victim_candidates"] + self._original["confirmed_victims"]
        } | {
            _identifier(item, ("detection_id", "victim_id", "id"))
            for item in self._edits["added_victims"]
        }
        if victim_id in all_ids:
            raise ValidationError("victim_id already exists")
        point = _point_dict(x, y)
        self._before_edit()
        self._edits["added_victims"].append(
            {
                "id": victim_id,
                "victim_id": victim_id,
                "label": "요구조자",
                "status": "confirmed",
                "x": point["x"],
                "y": point["y"],
                "map_position": point,
                "position": point,
                "source": "host_user",
                "host_status": "added",
                "confidence": 1.0,
            }
        )

    def remove_added_victim(self, victim_id: str) -> None:
        victim_id = str(victim_id)
        remaining = [
            item
            for item in self._edits["added_victims"]
            if _identifier(item, ("detection_id", "victim_id", "id")) != victim_id
        ]
        if len(remaining) == len(self._edits["added_victims"]):
            raise ValidationError("Host-added victim was not found")
        self._before_edit()
        self._edits["added_victims"] = remaining

    def set_route_approved(self, route_id: str, approved: bool) -> None:
        if not isinstance(approved, bool):
            raise ValidationError("approved must be boolean")
        route_id = str(route_id)
        known_route_ids = {
            _identifier(route, ("route_id", "id"))
            for layer in ("entry_routes", "return_routes")
            for route in self._original.get(layer, [])
        }
        if route_id not in known_route_ids:
            raise ValidationError("route was not found in the current review")
        self._before_edit()
        self._edits["route_approvals"][route_id] = approved

    def modify_risk_zone(self, risk_id: str, risk_zone: Mapping[str, Any]) -> None:
        risk_id = str(risk_id)
        original = next(
            (
                item
                for item in self._original["risk_zones"]
                if _identifier(item, ("risk_id", "id")) == risk_id
            ),
            None,
        )
        if original is None:
            raise ValidationError("risk zone was not found")
        merged = copy.deepcopy(dict(original))
        merged.update(copy.deepcopy(dict(risk_zone)))
        replacement = _validate_risk_zone(merged, risk_id=risk_id)
        self._before_edit()
        self._edits["risk_modifications"][risk_id] = replacement

    def clear_risk_zone(self, risk_id: str) -> None:
        self._before_edit()
        risk_id = str(risk_id)
        if risk_id not in self._edits["cleared_risk_ids"]:
            self._edits["cleared_risk_ids"].append(risk_id)

    def add_risk_zone(self, risk_zone: Mapping[str, Any]) -> None:
        replacement = _validate_risk_zone(risk_zone)
        risk_id = replacement["risk_id"]
        all_ids = {
            _identifier(item, ("risk_id", "id")) for item in self._original["risk_zones"]
        } | {
            _identifier(item, ("risk_id", "id"))
            for item in self._edits["added_risk_zones"]
        }
        if risk_id in all_ids:
            raise ValidationError("risk_id already exists")
        self._before_edit()
        self._edits["added_risk_zones"].append(replacement)

    def remove_added_risk_zone(self, risk_id: str) -> None:
        risk_id = str(risk_id)
        remaining = [
            item
            for item in self._edits["added_risk_zones"]
            if _identifier(item, ("risk_id", "id")) != risk_id
        ]
        if len(remaining) == len(self._edits["added_risk_zones"]):
            raise ValidationError("Host-added risk zone was not found")
        self._before_edit()
        self._edits["added_risk_zones"] = remaining

    def update_added_risk_zone(self, risk_id: str, risk_zone: Mapping[str, Any]) -> None:
        risk_id = str(risk_id)
        replacement = _validate_risk_zone(risk_zone)
        if replacement["risk_id"] != risk_id:
            raise ValidationError("risk_id cannot change while editing")
        current = copy.deepcopy(self._edits["added_risk_zones"])
        for index, item in enumerate(current):
            if _identifier(item, ("risk_id", "id")) == risk_id:
                current[index] = replacement
                self._before_edit()
                self._edits["added_risk_zones"] = current
                return
        raise ValidationError("Host-added risk zone was not found")

    def set_team_assignments(self, assignments: Sequence[Mapping[str, Any]]) -> None:
        validated = [_validate_assignment(item) for item in assignments]
        self._before_edit()
        self._edits["team_assignments"] = validated

    def upsert_team_assignment(self, assignment: Mapping[str, Any]) -> None:
        replacement = _validate_assignment(assignment)
        current = self._edits["team_assignments"]
        if current is None:
            current = [
                _validate_assignment(item)
                for item in self._original.get("team_recommendations", [])
            ]
        else:
            current = copy.deepcopy(current)
        current = [item for item in current if item.get("team_id") != replacement["team_id"]]
        current.append(replacement)
        self._before_edit()
        self._edits["team_assignments"] = current

    def remove_team_assignment(self, team_id: str) -> None:
        current = self._edits["team_assignments"]
        if current is None:
            current = [
                _validate_assignment(item)
                for item in self._original.get("team_recommendations", [])
            ]
        remaining = [item for item in current if item.get("team_id") != str(team_id)]
        if len(remaining) == len(current):
            raise ValidationError("team assignment was not found")
        self._before_edit()
        self._edits["team_assignments"] = remaining

    def set_safe_waiting_points(self, points: Sequence[Mapping[str, Any]]) -> None:
        validated = []
        for index, item in enumerate(_array(points, "safe_waiting_points")):
            point = Point.from_value(item, "safe waiting point")
            details = dict(item)
            details.update(
                {
                    "waiting_id": _waiting_id(details, index),
                    "x": point.x,
                    "y": point.y,
                    "host_status": "modified",
                }
            )
            validated.append(details)
        self._before_edit()
        self._edits["safe_waiting_points"] = validated

    def add_safe_waiting_point(self, waiting_id: str, x: float, y: float) -> None:
        waiting_id = str(waiting_id).strip()
        if not waiting_id:
            raise ValidationError("safe waiting point requires waiting_id")
        if any(
            _waiting_id(item) == waiting_id
            for item in self._edits["safe_waiting_points"]
        ):
            raise ValidationError("waiting_id already exists")
        self._before_edit()
        self._edits["safe_waiting_points"].append(
            {
                "waiting_id": waiting_id,
                **_point_dict(x, y),
                "source": "host_user",
                "host_status": "added",
            }
        )

    def update_safe_waiting_point(self, waiting_id: str, x: float, y: float) -> None:
        waiting_id = str(waiting_id)
        replacement = _point_dict(x, y)
        current = copy.deepcopy(self._edits["safe_waiting_points"])
        for item in current:
            if _waiting_id(item) == waiting_id:
                item.update(replacement)
                item["host_status"] = "modified"
                self._before_edit()
                self._edits["safe_waiting_points"] = current
                return
        raise ValidationError("safe waiting point was not found")

    def remove_safe_waiting_point(self, waiting_id: str) -> None:
        waiting_id = str(waiting_id)
        current = self._edits["safe_waiting_points"]
        remaining = [item for item in current if _waiting_id(item) != waiting_id]
        if len(remaining) == len(current):
            raise ValidationError("safe waiting point was not found")
        self._before_edit()
        self._edits["safe_waiting_points"] = remaining

    def set_notes(self, notes: str) -> None:
        if not isinstance(notes, str):
            raise ValidationError("notes must be text")
        self._before_edit()
        self._edits["notes"] = notes

    @property
    def reviewed_result(self) -> dict[str, Any]:
        result = copy.deepcopy(self._original)
        modifications = self._edits["victim_modifications"]
        for layer in ("victim_candidates", "confirmed_victims"):
            reviewed = []
            for item in result[layer]:
                item_id = _identifier(item, ("detection_id", "victim_id", "id"))
                item.update(copy.deepcopy(modifications.get(item_id, {})))
                if item_id in self._edits["victim_status"]:
                    item["host_status"] = self._edits["victim_status"][item_id]
                if item_id in self._edits["victim_priorities"]:
                    item["priority"] = self._edits["victim_priorities"][item_id]
                reviewed.append(item)
            result[layer] = reviewed
        result["confirmed_victims"].extend(copy.deepcopy(self._edits["added_victims"]))
        cleared = set(self._edits["cleared_risk_ids"])
        risk_modifications = self._edits["risk_modifications"]
        result["risk_zones"] = [
            copy.deepcopy(risk_modifications.get(risk_id, item))
            for item in result["risk_zones"]
            if (risk_id := _identifier(item, ("risk_id", "id"))) not in cleared
        ] + copy.deepcopy(self._edits["added_risk_zones"])
        for route in result["entry_routes"]:
            route_id = _identifier(route, ("route_id", "id"))
            if route_id in self._edits["route_approvals"]:
                route["host_status"] = (
                    "approved" if self._edits["route_approvals"][route_id] else "excluded"
                )
        if self._edits["team_assignments"] is not None:
            result["team_recommendations"] = copy.deepcopy(
                self._edits["team_assignments"]
            )
        result["safe_waiting_points"] = copy.deepcopy(
            self._edits["safe_waiting_points"]
        )
        return result

    def build_approved_plan(self, plan_version: int, modified_at: str | None = None) -> ApprovedPlan:
        candidates = copy.deepcopy(self._original["victim_candidates"])
        approved_victims = []
        for item in self._original["confirmed_victims"]:
            reviewed_confirmed = copy.deepcopy(item)
            item_id = _identifier(
                reviewed_confirmed, ("detection_id", "victim_id", "id")
            )
            reviewed_confirmed.update(
                copy.deepcopy(self._edits["victim_modifications"].get(item_id, {}))
            )
            reviewed_confirmed["host_status"] = self._edits["victim_status"].get(
                item_id, "confirmed"
            )
            if item_id in self._edits["victim_priorities"]:
                reviewed_confirmed["priority"] = self._edits["victim_priorities"][
                    item_id
                ]
            if reviewed_confirmed["host_status"] != "excluded":
                approved_victims.append(reviewed_confirmed)
        approved_victims.extend(copy.deepcopy(self._edits["added_victims"]))
        excluded: list[Mapping[str, Any]] = []
        for item in candidates:
            item_id = _identifier(item, ("detection_id", "victim_id", "id"))
            status = self._edits["victim_status"].get(item_id, "pending")
            reviewed = copy.deepcopy(item)
            reviewed.update(
                copy.deepcopy(self._edits["victim_modifications"].get(item_id, {}))
            )
            reviewed["host_status"] = status
            if item_id in self._edits["victim_priorities"]:
                reviewed["priority"] = self._edits["victim_priorities"][item_id]
            if status == "confirmed":
                approved_victims.append(reviewed)
            elif status == "excluded":
                excluded.append(reviewed)
        cleared = set(self._edits["cleared_risk_ids"])
        modifications = self._edits["risk_modifications"]
        approved_risks: list[Mapping[str, Any]] = []
        changed_risks: list[Mapping[str, Any]] = []
        for risk in self._original["risk_zones"]:
            risk_id = _identifier(risk, ("risk_id", "id"))
            if risk_id in cleared:
                changed_risks.append({"risk_id": risk_id, "host_status": "cleared"})
            elif risk_id in modifications:
                approved_risks.append(copy.deepcopy(modifications[risk_id]))
                changed_risks.append(copy.deepcopy(modifications[risk_id]))
            else:
                approved_risks.append(copy.deepcopy(risk))
        approved_risks.extend(copy.deepcopy(self._edits["added_risk_zones"]))
        changed_risks.extend(copy.deepcopy(self._edits["added_risk_zones"]))
        routes = []
        for route in self.reviewed_result["entry_routes"]:
            route_id = _identifier(route, ("route_id", "id"))
            if self._edits["route_approvals"].get(route_id, False):
                reviewed = copy.deepcopy(route)
                reviewed["host_status"] = "approved"
                routes.append(reviewed)
        assignments = self._edits["team_assignments"]
        if assignments is None:
            assignments = []
        priorities = [
            {"victim_id": victim_id, "priority": priority}
            for victim_id, priority in self._edits["victim_priorities"].items()
        ]
        plan = ApprovedPlan(
            mission_id=str(self._original["mission_id"]),
            mission_version=int(self._original["base_map_version"]),
            base_result_version=int(self._original["result_version"]),
            approved_plan_version=plan_version,
            modified_at=modified_at or utc_now(),
            coordinate_frame=str(self._original["coordinate_frame"]),
            approved_victims=tuple(approved_victims),
            excluded_victim_candidates=tuple(excluded),
            approved_risk_zones=tuple(approved_risks),
            modified_or_cleared_risk_zones=tuple(changed_risks),
            final_team_assignments=tuple(assignments),
            approved_routes=tuple(routes),
            priorities=tuple(priorities),
            safe_waiting_points=tuple(self._edits["safe_waiting_points"]),
            notes=self._edits["notes"],
        )
        self._final_approved = plan.to_dict()
        return plan
