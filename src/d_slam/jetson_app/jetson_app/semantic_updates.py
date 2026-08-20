"""Deterministic semantic change detection for continuous Jetson updates."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

SEMANTIC_KEYS = (
    "robot_pose",
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
    "map_alignment",
)
VOLATILE_KEYS = {"created_at", "artifact_version", "result_version", "slam_map_version"}
ID_KEYS = (
    "detection_id", "victim_id", "risk_id", "route_id", "team_id", "waiting_id", "id"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _stable_id(value: Any) -> str:
    if isinstance(value, Mapping):
        for key in ID_KEYS:
            item = value.get(key)
            if item not in {None, ""}:
                return f"{key}:{item}"
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _normalize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _normalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if key not in VOLATILE_KEYS
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        normalized = [_normalize(item) for item in value]
        if all(isinstance(item, Mapping) for item in normalized):
            return sorted(normalized, key=_stable_id)
        return normalized
    if isinstance(value, float):
        if not math.isfinite(value):
            return value
        return round(value, 3)
    return value


def normalized_semantic(result: Mapping[str, Any]) -> dict[str, Any]:
    return {key: _normalize(result.get(key)) for key in SEMANTIC_KEYS if key in result}


def semantic_fingerprint(result: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        normalized_semantic(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _entity_map(values: Any) -> dict[str, Mapping[str, Any]]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        return {}
    result: dict[str, Mapping[str, Any]] = {}
    for item in values:
        if isinstance(item, Mapping):
            result[_stable_id(item)] = item
    return result


def _critical_risk(value: Mapping[str, Any]) -> bool:
    try:
        return float(value.get("severity", 0.0)) >= 0.8
    except (TypeError, ValueError):
        return False


def _event_id(event_type: str, identity: str, payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        _normalize(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    digest = hashlib.sha256(f"{event_type}|{identity}|{canonical}".encode()).hexdigest()[:20]
    return f"{event_type}-{digest}"


@dataclass(frozen=True)
class SemanticUpdateBatch:
    changed: bool
    delta: Mapping[str, Any] | None = None
    urgent_events: tuple[Mapping[str, Any], ...] = ()
    changed_keys: tuple[str, ...] = ()


class SemanticChangeDetector:
    """Compare stable semantic content, never timestamps or bare map versions."""

    def __init__(self) -> None:
        self._previous: dict[str, Any] | None = None
        self._previous_fingerprint: str | None = None
        self._seen_event_ids: set[str] = set()

    @property
    def has_baseline(self) -> bool:
        return self._previous is not None

    @property
    def previous(self) -> dict[str, Any] | None:
        return copy.deepcopy(self._previous)

    def reset(self) -> None:
        self._previous = None
        self._previous_fingerprint = None
        self._seen_event_ids.clear()

    def seed(self, result: Mapping[str, Any]) -> None:
        self._previous = copy.deepcopy(dict(result))
        self._previous_fingerprint = semantic_fingerprint(result)

    def observe(self, current: Mapping[str, Any]) -> SemanticUpdateBatch:
        current_dict = copy.deepcopy(dict(current))
        fingerprint = semantic_fingerprint(current_dict)
        previous = self._previous
        if previous is None:
            self.seed(current_dict)
            return SemanticUpdateBatch(changed=True)
        if fingerprint == self._previous_fingerprint:
            return SemanticUpdateBatch(changed=False)

        old_normalized = normalized_semantic(previous)
        new_normalized = normalized_semantic(current_dict)
        changed_keys = tuple(
            key for key in SEMANTIC_KEYS if old_normalized.get(key) != new_normalized.get(key)
        )
        if not changed_keys:
            return SemanticUpdateBatch(changed=False)

        base_version = int(previous.get("result_version", 0))
        result_version = int(current_dict.get("result_version", 0))
        if base_version < 1 or result_version != base_version + 1:
            raise ValueError(
                "semantic change versions must be contiguous: "
                f"base={base_version}, result={result_version}"
            )
        updates = {key: copy.deepcopy(current_dict.get(key)) for key in changed_keys}
        changed_regions = copy.deepcopy(current_dict.get("changed_regions", []))
        if not isinstance(changed_regions, list):
            changed_regions = []
        delta = {
            "schema_version": "1.0",
            "mission_id": current_dict["mission_id"],
            "artifact_version": result_version,
            "base_result_version": base_version,
            "result_version": result_version,
            "base_map_version": current_dict.get("base_map_version"),
            "slam_map_version": current_dict.get("slam_map_version"),
            "analysis_mode": current_dict.get("analysis_mode", "unknown"),
            "created_at": utc_now(),
            "coordinate_frame": "mission_map",
            "source": "jetson_semantic_change_monitor",
            "confidence": float(current_dict.get("confidence", 0.0)),
            "changed_regions": changed_regions,
            "semantic_updates": updates,
        }
        urgent = self._urgent_events(previous, current_dict, result_version)
        self.seed(current_dict)
        return SemanticUpdateBatch(True, delta, urgent, changed_keys)

    def _urgent_events(
        self, previous: Mapping[str, Any], current: Mapping[str, Any], result_version: int
    ) -> tuple[Mapping[str, Any], ...]:
        events: list[Mapping[str, Any]] = []

        # A newly discovered candidate is urgent even before Host confirmation.
        seen_victim_ids: set[str] = set()
        for layer in ("confirmed_victims", "victim_candidates"):
            old_victims = _entity_map(previous.get(layer, []))
            new_victims = _entity_map(current.get(layer, []))
            for identity in sorted(set(new_victims) - set(old_victims)):
                if identity in seen_victim_ids:
                    continue
                seen_victim_ids.add(identity)
                victim = copy.deepcopy(dict(new_victims[identity]))
                events.append(
                    self._build_event(
                        current,
                        result_version,
                        "new_victim",
                        identity,
                        {"victim": victim, "semantic_layer": layer, "result_version": result_version},
                        priority=255,
                    )
                )

        old_risks = _entity_map(previous.get("risk_zones", []))
        new_risks = _entity_map(current.get("risk_zones", []))
        for identity, risk in sorted(new_risks.items()):
            if not _critical_risk(risk):
                continue
            old = old_risks.get(identity)
            if old is not None and _normalize(old) == _normalize(risk):
                continue
            events.append(
                self._build_event(
                    current, result_version, "critical_risk", identity,
                    {"risk": copy.deepcopy(dict(risk)), "result_version": result_version},
                    priority=250,
                )
            )

        old_routes = _entity_map(previous.get("entry_routes", []))
        new_routes = _entity_map(current.get("entry_routes", []))
        for identity in sorted(set(old_routes) - set(new_routes)):
            events.append(
                self._build_event(
                    current, result_version, "route_blocked", identity,
                    {
                        "route_id": identity.split(":", 1)[-1],
                        "previous_route": copy.deepcopy(dict(old_routes[identity])),
                        "result_version": result_version,
                    },
                    priority=245,
                )
            )
        for identity, route in sorted(new_routes.items()):
            status = str(route.get("status", route.get("state", ""))).lower()
            if status not in {"blocked", "closed", "unavailable"}:
                continue
            old = old_routes.get(identity)
            if old is not None and _normalize(old) == _normalize(route):
                continue
            events.append(
                self._build_event(
                    current, result_version, "route_blocked", identity,
                    {"route": copy.deepcopy(dict(route)), "result_version": result_version},
                    priority=245,
                )
            )

        unique: list[Mapping[str, Any]] = []
        for event in events:
            event_id = str(event["event_id"])
            if event_id in self._seen_event_ids:
                continue
            self._seen_event_ids.add(event_id)
            unique.append(event)
        return tuple(unique)

    def mission_error(
        self, mission_id: str, artifact_version: int, error: BaseException
    ) -> Mapping[str, Any] | None:
        payload = {
            "error_code": type(error).__name__,
            "message": str(error),
            "result_version": int(artifact_version),
        }
        event = self._build_event(
            {"mission_id": mission_id, "confidence": 1.0},
            max(1, int(artifact_version)), "mission_error", type(error).__name__, payload,
            priority=255,
        )
        event_id = str(event["event_id"])
        if event_id in self._seen_event_ids:
            return None
        self._seen_event_ids.add(event_id)
        return event

    @staticmethod
    def _build_event(
        current: Mapping[str, Any], artifact_version: int, event_type: str,
        identity: str, payload: Mapping[str, Any], *, priority: int,
    ) -> Mapping[str, Any]:
        return {
            "schema_version": "1.0",
            "mission_id": str(current["mission_id"]),
            "artifact_version": max(1, int(artifact_version)),
            "event_id": _event_id(event_type, identity, payload),
            "event_type": event_type,
            "created_at": utc_now(),
            "coordinate_frame": "mission_map",
            "source": "jetson_semantic_change_monitor",
            "confidence": float(current.get("confidence", 1.0)),
            "priority": int(priority),
            "payload": copy.deepcopy(dict(payload)),
        }


__all__ = ["SemanticChangeDetector", "SemanticUpdateBatch", "normalized_semantic", "semantic_fingerprint"]
