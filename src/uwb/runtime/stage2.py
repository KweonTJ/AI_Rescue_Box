"""Stage 2 Host↔Jetson application handoff on top of the existing UWB runtime.

The protocol/spool layer remains responsible for frame reliability and peer
storage.  This module owns only the application boundary: pair a mission map
with its manifest, hand it to d_slam through a port, and emit application ACKs
only after the application reports success.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

from .coordinator import MissionArtifactCoordinator
from .map_preview_sender import MapPreviewSender
from .mission_artifacts import ReceivedMissionArtifact
from .mission_artifacts import verify_sha256
from .ports import ApplicationAckPort, ArtifactSenderPort
from .result_sender import SemanticResultSender


@dataclass(frozen=True)
class ApplicationResult:
    success: bool
    state: str
    error_code: str = ""
    message: str = ""


class MissionApplicationPort(Protocol):
    def load_mission(
        self,
        *,
        mission_id: str,
        mission_version: int,
        base_map_path: Path,
        mission_manifest_path: Path,
    ) -> ApplicationResult: ...

    def apply_approved_plan(
        self,
        *,
        mission_id: str,
        mission_version: int,
        approved_plan_version: int,
        approved_plan_path: Path,
    ) -> ApplicationResult: ...


def _read_object(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"artifact JSON could not be read: {error}") from error
    if not isinstance(value, Mapping):
        raise ValueError("artifact JSON root must be an object")
    return value


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _manifest_base_map_sha256(manifest: Mapping[str, Any]) -> str:
    nested = manifest.get("base_map")
    if isinstance(nested, Mapping) and isinstance(nested.get("sha256"), str):
        return str(nested["sha256"])
    value = manifest.get("base_map_sha256")
    if not isinstance(value, str):
        raise ValueError("mission manifest does not contain base map SHA-256")
    return value


class JetsonStage2Runtime:
    """Connect received UWB artifacts to d_slam without importing d_slam internals."""

    def __init__(
        self,
        application: MissionApplicationPort,
        acknowledgements: ApplicationAckPort,
        sender: ArtifactSenderPort | None = None,
    ) -> None:
        self._application = application
        self._acks = acknowledgements
        self._coordinator = MissionArtifactCoordinator()
        self._result_sender = SemanticResultSender(sender) if sender is not None else None
        self._preview_sender = MapPreviewSender(sender) if sender is not None else None

    def handle_received(self, artifact: ReceivedMissionArtifact) -> str:
        if artifact.artifact_type == "approved_plan":
            return self._apply_approved_plan(artifact)
        if artifact.artifact_type not in {"base_map", "mission_manifest"}:
            return "ignored"
        try:
            verify_sha256(artifact.local_file_path, artifact.sha256)
            pair = self._coordinator.observe(artifact)
        except Exception as error:
            self._acks.acknowledge(
                artifact.transfer_id, applied=False, error_message=str(error)
            )
            return "rejected"
        if pair is None:
            return "pending"

        transfers = (pair.base_map.transfer_id, pair.manifest.transfer_id)
        try:
            verify_sha256(pair.base_map.local_file_path, pair.base_map.sha256)
            verify_sha256(pair.manifest.local_file_path, pair.manifest.sha256)
            manifest = _read_object(pair.manifest.local_file_path)
            mission_id = str(manifest.get("mission_id", ""))
            mission_version = _positive_int(
                manifest.get("mission_version"), "mission_version"
            )
            artifact_version = _positive_int(
                manifest.get("artifact_version", mission_version), "artifact_version"
            )
            if mission_id != pair.mission_id:
                raise ValueError("mission manifest mission_id differs from UWB metadata")
            if mission_version != pair.artifact_version:
                raise ValueError("mission manifest mission_version differs from UWB metadata")
            if artifact_version != pair.artifact_version:
                raise ValueError("mission manifest artifact_version differs from UWB metadata")
            if _manifest_base_map_sha256(manifest) != pair.base_map.sha256:
                raise ValueError("base map SHA-256 differs from mission manifest")
            result = self._application.load_mission(
                mission_id=mission_id,
                mission_version=mission_version,
                base_map_path=pair.base_map.local_file_path,
                mission_manifest_path=pair.manifest.local_file_path,
            )
            if not result.success or result.state != "READY":
                raise RuntimeError(
                    result.message
                    or result.error_code
                    or f"d_slam rejected mission with state {result.state}"
                )
        except Exception as error:
            for transfer_id in transfers:
                self._acks.acknowledge(
                    transfer_id, applied=False, error_message=str(error)
                )
            self._coordinator.forget(pair.mission_id, pair.artifact_version)
            return "rejected"

        for transfer_id in transfers:
            self._acks.acknowledge(transfer_id, applied=True)
        self._coordinator.forget(pair.mission_id, pair.artifact_version)
        return "ready"

    def _apply_approved_plan(self, artifact: ReceivedMissionArtifact) -> str:
        try:
            verify_sha256(artifact.local_file_path, artifact.sha256)
            plan = _read_object(artifact.local_file_path)
            mission_id = str(plan.get("mission_id", ""))
            mission_version = _positive_int(
                plan.get("mission_version"), "mission_version"
            )
            plan_version = _positive_int(
                plan.get("approved_plan_version"), "approved_plan_version"
            )
            payload_artifact_version = _positive_int(
                plan.get("artifact_version", plan_version), "artifact_version"
            )
            if mission_id != artifact.mission_id:
                raise ValueError("approved plan mission_id differs from UWB metadata")
            if plan_version != artifact.artifact_version:
                raise ValueError("approved plan version differs from UWB metadata")
            if payload_artifact_version != plan_version:
                raise ValueError("approved plan artifact_version differs from plan version")
            result = self._application.apply_approved_plan(
                mission_id=mission_id,
                mission_version=mission_version,
                approved_plan_version=plan_version,
                approved_plan_path=artifact.local_file_path,
            )
            if not result.success or result.state not in {"APPLIED", "READY"}:
                raise RuntimeError(
                    result.message
                    or result.error_code
                    or f"d_slam rejected approved plan with state {result.state}"
                )
        except Exception as error:
            self._acks.acknowledge(
                artifact.transfer_id, applied=False, error_message=str(error)
            )
            return "rejected"
        self._acks.acknowledge(artifact.transfer_id, applied=True)
        return "applied"

    def return_analysis(
        self,
        semantic_result_path: Path,
        map_preview_path: Path,
    ) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        if self._result_sender is None or self._preview_sender is None:
            raise RuntimeError("artifact sender is not configured")
        result = _read_object(semantic_result_path)
        mission_id = str(result.get("mission_id", ""))
        if not mission_id:
            raise ValueError("semantic_result mission_id is required")
        result_version = _positive_int(result.get("result_version"), "result_version")
        artifact_version = _positive_int(
            result.get("artifact_version", result_version), "artifact_version"
        )
        if artifact_version != result_version:
            raise ValueError("semantic_result artifact_version must match result_version")
        if result.get("coordinate_frame") != "mission_map":
            raise ValueError("semantic_result coordinate_frame must be mission_map")
        result_transfer = self._result_sender.send(
            Path(semantic_result_path),
            mission_id=mission_id,
            result_version=result_version,
        )
        preview_transfer = self._preview_sender.send(
            Path(map_preview_path),
            mission_id=mission_id,
            artifact_version=result_version,
        )
        return result_transfer, preview_transfer


__all__ = [
    "ApplicationResult",
    "JetsonStage2Runtime",
    "MissionApplicationPort",
]
