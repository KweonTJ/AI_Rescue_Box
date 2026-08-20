"""Global AI Boost entry point for UWB semantic transmission policy."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class AiBoostDecision:
    transmit: bool
    priority: int
    compression: str
    reason: str


class AiBoostModel(Protocol):
    def decide(self, artifact_type: str, payload: Mapping[str, Any]) -> Mapping[str, Any]: ...


def _deterministic_decision(
    artifact_type: str, payload: Mapping[str, Any], requested_priority: int
) -> AiBoostDecision:
    kind = str(artifact_type)
    requested = max(0, min(255, int(requested_priority)))
    if kind == "urgent_event":
        event_type = str(payload.get("event_type", ""))
        if event_type in {"new_victim", "critical_risk", "mission_error"}:
            return AiBoostDecision(True, max(requested, 255), "none", event_type or "urgent")
        if event_type == "route_blocked":
            return AiBoostDecision(True, max(requested, 245), "none", "route_blocked")
        return AiBoostDecision(True, max(requested, 235), "none", "urgent_event")
    if kind == "map_delta":
        return AiBoostDecision(True, max(requested, 180), "none", "semantic_change")
    if kind == "semantic_result":
        return AiBoostDecision(True, max(requested, 200), "none", "initial_semantic_state")
    if kind == "approved_plan":
        return AiBoostDecision(True, max(requested, 220), "none", "operator_approved")
    if kind in {"mission_manifest", "base_map"}:
        return AiBoostDecision(True, max(requested, 210), "none", "mission")
    if kind == "map_preview":
        return AiBoostDecision(True, max(requested, 20), "none", "manual_low_priority_preview")
    return AiBoostDecision(True, max(requested, 100), "none", "default")


def ai_boost(
    artifact_type: str,
    payload: Mapping[str, Any] | None = None,
    *,
    requested_priority: int = 0,
    enabled: bool = False,
    model: AiBoostModel | None = None,
) -> AiBoostDecision:
    data = dict(payload or {})
    fallback = _deterministic_decision(artifact_type, data, requested_priority)
    if not enabled or model is None:
        return fallback
    try:
        suggestion = dict(model.decide(str(artifact_type), data))
        priority = max(0, min(255, int(suggestion.get("priority", fallback.priority))))
        return AiBoostDecision(
            bool(suggestion.get("transmit", fallback.transmit)),
            priority,
            str(suggestion.get("compression", fallback.compression)),
            str(suggestion.get("reason", "model_advisory")),
        )
    except Exception:
        return fallback


__all__ = ["AiBoostDecision", "AiBoostModel", "ai_boost"]
