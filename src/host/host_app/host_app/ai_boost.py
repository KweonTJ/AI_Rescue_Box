"""Global AI Boost entry point for Host semantic reconstruction."""
from __future__ import annotations

import copy
from typing import Any, Mapping, Protocol


class AiBoostModel(Protocol):
    def reconstruct(
        self, previous: Mapping[str, Any], delta: Mapping[str, Any], prior_map_metadata: Mapping[str, Any]
    ) -> Mapping[str, Any]: ...


def _deterministic_reconstruction(
    previous: Mapping[str, Any], delta: Mapping[str, Any]
) -> dict[str, Any]:
    current = copy.deepcopy(dict(previous))
    base_version = int(delta.get("base_result_version", 0))
    result_version = int(delta.get("result_version", 0))
    if int(current.get("result_version", 0)) != base_version:
        raise ValueError(
            "map_delta base_result_version does not match reconstructed state: "
            f"expected {current.get('result_version')}, got {base_version}"
        )
    if result_version != base_version + 1:
        raise ValueError("map_delta result_version must be contiguous")
    if str(delta.get("mission_id", "")) != str(current.get("mission_id", "")):
        raise ValueError("map_delta mission_id does not match semantic state")
    updates = delta.get("semantic_updates", {})
    if not isinstance(updates, Mapping):
        raise ValueError("map_delta semantic_updates must be an object")
    for key, value in updates.items():
        current[str(key)] = copy.deepcopy(value)
    current["result_version"] = result_version
    current["artifact_version"] = result_version
    for key in ("slam_map_version", "analysis_mode", "confidence"):
        if key in delta and delta[key] is not None:
            current[key] = copy.deepcopy(delta[key])
    if "base_map_version" in delta and delta["base_map_version"] is not None:
        if int(delta["base_map_version"]) != int(current.get("base_map_version", 0)):
            raise ValueError("map_delta base_map_version does not match semantic state")
    if "created_at" in delta:
        current["created_at"] = delta["created_at"]
    current["source"] = "host_reconstructed_semantic_delta"
    return current


def ai_boost(
    previous: Mapping[str, Any],
    delta: Mapping[str, Any],
    prior_map_metadata: Mapping[str, Any] | None = None,
    *,
    enabled: bool = False,
    model: AiBoostModel | None = None,
) -> dict[str, Any]:
    fallback = _deterministic_reconstruction(previous, delta)
    if not enabled or model is None:
        return fallback
    try:
        candidate = model.reconstruct(previous, delta, prior_map_metadata or {})
        if not isinstance(candidate, Mapping):
            return fallback
        value = copy.deepcopy(dict(candidate))
        if value.get("mission_id") != fallback.get("mission_id"):
            return fallback
        if value.get("result_version") != fallback.get("result_version"):
            return fallback
        return value
    except Exception:
        return fallback


__all__ = ["AiBoostModel", "ai_boost"]
