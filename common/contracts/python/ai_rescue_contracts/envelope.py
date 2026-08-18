"""Artifact envelope validation without ROS, Pydantic or model dependencies."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import Enum

MISSION_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class ContractError(ValueError):
    pass


class ArtifactType(str, Enum):
    BASE_MAP = "base_map"
    MISSION_MANIFEST = "mission_manifest"
    APPROVED_PLAN = "approved_plan"
    SEMANTIC_RESULT = "semantic_result"
    MAP_PREVIEW = "map_preview"
    URGENT_EVENT = "urgent_event"
    MAP_DELTA = "map_delta"
    MISSION_ACK = "mission_ack"


@dataclass(frozen=True)
class ArtifactEnvelope:
    artifact_type: ArtifactType
    mission_id: str
    artifact_version: int
    sha256: str
    source: str
    confidence: float = 1.0
    coordinate_frame: str = "mission_map"
    units: str = "meters"
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        if self.schema_version != "1.0":
            raise ContractError("unsupported schema_version")
        if MISSION_ID_RE.fullmatch(self.mission_id) is None:
            raise ContractError("invalid mission_id")
        if isinstance(self.artifact_version, bool) or self.artifact_version < 1:
            raise ContractError("artifact_version must be a positive integer")
        if SHA256_RE.fullmatch(self.sha256) is None:
            raise ContractError("sha256 must be 64 lowercase hex characters")
        if not self.source:
            raise ContractError("source is required")
        if not math.isfinite(float(self.confidence)) or not 0.0 <= self.confidence <= 1.0:
            raise ContractError("confidence must be in [0, 1]")
        if self.units not in {"meters", "m", "pixels", "bytes"}:
            raise ContractError("unsupported units")
