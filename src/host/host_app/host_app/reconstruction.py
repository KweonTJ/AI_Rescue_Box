from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .ai_boost import ai_boost


class ReconstructionStrategy(Protocol):
    def reconstruct(
        self, *, previous: Mapping[str, Any] | None, delta: Mapping[str, Any] | None,
        semantic_result: Mapping[str, Any] | None,
    ) -> Mapping[str, Any]: ...


class DeterministicReconstructionStrategy:
    def reconstruct(
        self, *, previous: Mapping[str, Any] | None, delta: Mapping[str, Any] | None,
        semantic_result: Mapping[str, Any] | None,
    ) -> Mapping[str, Any]:
        if semantic_result is not None:
            return copy.deepcopy(dict(semantic_result))
        if previous is None or delta is None:
            raise ValueError("previous state and delta are required")
        return ai_boost(previous, delta, enabled=False)


@dataclass(frozen=True)
class ReconstructionOutcome:
    state: Mapping[str, Any]
    applied: bool
    duplicate: bool = False
    stale: bool = False


class VersionGapError(ValueError):
    pass


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


class HostSemanticReconstructor:
    """Version-aware semantic_result + map_delta accumulator."""

    def __init__(self, strategy: ReconstructionStrategy | None = None) -> None:
        self.strategy = strategy or DeterministicReconstructionStrategy()
        self._states: dict[tuple[str, int], dict[str, Any]] = {}
        self._digests: dict[tuple[str, str, int, int], str] = {}

    def current(self, mission_id: str, base_map_version: int) -> Mapping[str, Any] | None:
        value = self._states.get((mission_id, int(base_map_version)))
        return copy.deepcopy(value) if value is not None else None

    def apply_semantic_result(self, result: Mapping[str, Any]) -> ReconstructionOutcome:
        mission_id = str(result.get("mission_id", ""))
        base = int(result.get("base_map_version", 0))
        version = int(result.get("result_version", 0))
        if not mission_id or base < 1 or version < 1:
            raise ValueError("semantic_result identity/version is invalid")
        key = ("semantic_result", mission_id, base, version)
        digest = _digest(result)
        previous_digest = self._digests.get(key)
        if previous_digest is not None:
            if previous_digest != digest:
                raise ValueError("duplicate semantic_result version has different content")
            state = self._states[(mission_id, base)]
            return ReconstructionOutcome(copy.deepcopy(state), False, duplicate=True)
        current = self._states.get((mission_id, base))
        if current is not None:
            current_version = int(current.get("result_version", 0))
            if version < current_version:
                return ReconstructionOutcome(copy.deepcopy(current), False, stale=True)
            if version == current_version:
                raise ValueError("semantic_result current version has different content")
        state = dict(self.strategy.reconstruct(previous=current, delta=None, semantic_result=result))
        self._states[(mission_id, base)] = copy.deepcopy(state)
        self._digests[key] = digest
        return ReconstructionOutcome(copy.deepcopy(state), True)

    def apply_delta(self, delta: Mapping[str, Any]) -> ReconstructionOutcome:
        mission_id = str(delta.get("mission_id", ""))
        base_result = int(delta.get("base_result_version", 0))
        result_version = int(delta.get("result_version", 0))
        artifact_version = int(delta.get("artifact_version", 0))
        if not mission_id or base_result < 1 or result_version < 1:
            raise ValueError("map_delta identity/version is invalid")
        if result_version != base_result + 1 or artifact_version != result_version:
            raise ValueError("map_delta versions must be contiguous and match artifact_version")
        candidates = [key for key in self._states if key[0] == mission_id]
        if not candidates:
            raise VersionGapError("map_delta arrived before semantic_result baseline")
        matching = [
            key for key in candidates
            if int(self._states[key].get("result_version", 0)) == base_result
        ]
        if not matching:
            latest_key = max(
                candidates, key=lambda key: int(self._states[key].get("result_version", 0))
            )
            latest = self._states[latest_key]
            latest_version = int(latest.get("result_version", 0))
            if result_version <= latest_version:
                digest_key = ("map_delta", mission_id, latest_key[1], result_version)
                known = self._digests.get(digest_key)
                if known is not None and known == _digest(delta):
                    return ReconstructionOutcome(copy.deepcopy(latest), False, duplicate=True)
                return ReconstructionOutcome(copy.deepcopy(latest), False, stale=True)
            raise VersionGapError(
                f"map_delta gap: Host has v{latest_version}, delta requires v{base_result}"
            )
        if len(matching) != 1:
            raise VersionGapError("ambiguous map_delta base across mission versions")
        state_key = matching[0]
        previous = self._states[state_key]
        digest_key = ("map_delta", mission_id, state_key[1], result_version)
        digest = _digest(delta)
        known = self._digests.get(digest_key)
        if known is not None:
            if known != digest:
                raise ValueError("duplicate map_delta version has different content")
            return ReconstructionOutcome(copy.deepcopy(previous), False, duplicate=True)
        state = dict(self.strategy.reconstruct(previous=previous, delta=delta, semantic_result=None))
        self._states[state_key] = copy.deepcopy(state)
        self._digests[digest_key] = digest
        return ReconstructionOutcome(copy.deepcopy(state), True)


__all__ = [
    "DeterministicReconstructionStrategy", "HostSemanticReconstructor",
    "ReconstructionOutcome", "ReconstructionStrategy", "VersionGapError",
]
