"""Dependency-injectable application service behind the Host HTTP API."""

from __future__ import annotations

import copy
import os
import re
import shutil
import threading
import uuid
from concurrent.futures import Future
from dataclasses import asdict
from pathlib import Path, PurePath
from typing import Any, Mapping

from ..errors import HostAppError, StaleVersionError, ValidationError
from ..map_editor import (
    CoordinateTransform,
    ImportedMap,
    MapImporter,
    NormalizationOptions,
    Point,
    RasterMapImporter,
    calculate_scale,
    read_map_preview_metadata,
)
from ..map_editor.importers import sha256_file
from ..mission.models import MissionManifest, SemanticResult, positive_int, utc_now
from ..mission.review import ApprovedPlan, ReviewSession
from ..mission.service import create_manifest, new_mission_id
from ..mission.workflow import HostTransferWorkflow, ReceivedArtifactLoader
from ..ros_client import BridgeStatus, HostBridgeFacade
from ..storage import MissionStore, SpoolManager
from ..storage.atomic import atomic_write_bytes, atomic_write_json
from .events import EventHub


SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
RESULT_FILE_RE = re.compile(r"semantic_result_v([1-9][0-9]*)\.json\Z")
PREVIEW_FILE_RE = re.compile(r"map_preview_v([1-9][0-9]*)\.png\Z")
PLAN_FILE_RE = re.compile(r"approved_plan_v([1-9][0-9]*)\.json\Z")


class ResourceNotFoundError(HostAppError):
    """An API-addressable map, mission, result, review, or operation is absent."""


class HostApiService:
    """Coordinate existing Host domain services without exposing ROS to clients."""

    def __init__(
        self,
        data_root: Path,
        *,
        bridge: HostBridgeFacade | None = None,
        importer: MapImporter | None = None,
        store: MissionStore | None = None,
        spool: SpoolManager | None = None,
        workflow: HostTransferWorkflow | None = None,
        normalization_options: NormalizationOptions | None = None,
        event_hub: EventHub | None = None,
        max_artifact_bytes: int = 10 * 1024 * 1024,
        transfer_timeout: float = 45.0,
    ) -> None:
        self.data_root = Path(data_root).expanduser().resolve()
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.normalization_options = normalization_options or NormalizationOptions()
        self.importer = importer or RasterMapImporter()
        self.events = event_hub or EventHub()
        self.store = store or MissionStore(
            self.data_root,
            max_original_map_bytes=self.normalization_options.max_input_bytes,
        )
        self.spool = spool or SpoolManager(
            self.data_root, max_file_bytes=max_artifact_bytes
        )
        workflow_bridge = getattr(workflow, "bridge", None)
        if bridge is not None and workflow_bridge is not None and workflow_bridge is not bridge:
            raise ValueError("workflow and service must use the same bridge facade")
        self._owns_bridge = bridge is None and workflow_bridge is None
        self.bridge = bridge or workflow_bridge or HostBridgeFacade()
        self.workflow = workflow or HostTransferWorkflow(
            self.bridge, transfer_timeout=transfer_timeout
        )
        self._lock = threading.RLock()
        self._storage_lock = threading.RLock()
        self._reviews: dict[tuple[str, int, int], ReviewSession] = {}
        self._review_revisions: dict[tuple[str, int, int], int] = {}
        self._operations: dict[str, dict[str, Any]] = {}
        self._active_mission: tuple[str, int] | None = None
        self._uploads_root = self.data_root / "api_uploads"
        self._uploads_root.mkdir(parents=True, exist_ok=True)
        self.bridge.add_status_listener(self._on_bridge_status)
        self.loader = ReceivedArtifactLoader(
            self.bridge,
            expected_mission_id=self._active_mission_id,
            expected_base_map_version=self._active_mission_version,
            on_semantic_result=self._apply_received_semantic,
            on_map_preview=self._apply_received_preview,
            on_error=self._on_received_error,
            max_file_bytes=max_artifact_bytes,
        )

    @staticmethod
    def _bridge_status_value(status: BridgeStatus) -> dict[str, Any]:
        value = asdict(status)
        value["state"] = status.state.value
        return value

    def _on_bridge_status(self, status: BridgeStatus) -> None:
        self.events.publish("bridge.status", self._bridge_status_value(status))

    def _active_mission_id(self) -> str | None:
        with self._lock:
            return self._active_mission[0] if self._active_mission else None

    def _active_mission_version(self) -> int | None:
        with self._lock:
            return self._active_mission[1] if self._active_mission else None

    @staticmethod
    def _safe_identifier(value: str, name: str) -> str:
        if not isinstance(value, str) or SAFE_ID_RE.fullmatch(value) is None:
            raise ValidationError(f"{name} is invalid")
        return value

    @staticmethod
    def _safe_upload_filename(filename: str) -> tuple[str, str]:
        if (
            not isinstance(filename, str)
            or not filename
            or len(filename) > 255
            or filename != PurePath(filename).name
            or "/" in filename
            or "\\" in filename
            or "\x00" in filename
        ):
            raise ValidationError("filename must be a single safe file name")
        suffix = Path(filename).suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png"}:
            raise ValidationError("map upload must use a JPEG or PNG filename")
        return filename, suffix

    def upload_map(self, filename: str, content: bytes) -> dict[str, Any]:
        """Persist the exact request bytes, then invoke RasterMapImporter."""

        source_filename, suffix = self._safe_upload_filename(filename)
        if not isinstance(content, bytes):
            raise ValidationError("map upload body must be raw bytes")
        if not 0 < len(content) <= self.normalization_options.max_input_bytes:
            raise ValidationError("map upload size is outside the allowed range")
        map_id = f"map-{uuid.uuid4().hex}"
        directory = self._uploads_root / map_id
        staging = self._uploads_root / f".{map_id}-{uuid.uuid4().hex}.part"
        original = staging / f"original{suffix}"
        try:
            atomic_write_bytes(original, content)
            imported = self.importer.import_map(
                original, staging / "normalized", self.normalization_options
            )
            if imported.file_size > self.spool.max_file_bytes:
                raise ValidationError(
                    "normalized map exceeds the configured UWB artifact limit"
                )
            metadata = {
                "map_id": map_id,
                "source_filename": source_filename,
                "original_filename": original.name,
                "transmission_filename": imported.transmission_path.name,
                "image_format": imported.image_format,
                "original_width": imported.original_width,
                "original_height": imported.original_height,
                "width": imported.width,
                "height": imported.height,
                "file_size": imported.file_size,
                "sha256": imported.sha256,
                "uploaded_at": utc_now(),
            }
            atomic_write_json(staging / "map.json", metadata)
            os.replace(staging, directory)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        response = self._public_map(metadata)
        self.events.publish("map.uploaded", response)
        return response

    @staticmethod
    def _public_map(metadata: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: copy.deepcopy(metadata[key])
            for key in (
                "map_id",
                "source_filename",
                "image_format",
                "original_width",
                "original_height",
                "width",
                "height",
                "file_size",
                "sha256",
                "uploaded_at",
            )
        }

    def _map_metadata(self, map_id: str) -> dict[str, Any]:
        map_id = self._safe_identifier(map_id, "map_id")
        path = self._uploads_root / map_id / "map.json"
        if not path.is_file() or path.is_symlink():
            raise ResourceNotFoundError("uploaded map was not found")
        value = self.store.load_json(path)
        if value.get("map_id") != map_id:
            raise ValidationError("stored map identity does not match its directory")
        return value

    def get_map(self, map_id: str) -> dict[str, Any]:
        return self._public_map(self._map_metadata(map_id))

    def uploaded_map_path(self, map_id: str) -> Path:
        return self._imported_map(map_id).transmission_path

    def list_maps(self) -> list[dict[str, Any]]:
        values = []
        for path in sorted(self._uploads_root.glob("*/map.json")):
            if (
                path.is_symlink()
                or path.parent.is_symlink()
                or SAFE_ID_RE.fullmatch(path.parent.name) is None
            ):
                continue
            try:
                metadata = self.store.load_json(path)
                if metadata.get("map_id") == path.parent.name:
                    values.append(self._public_map(metadata))
            except ValidationError:
                continue
        return values

    def _imported_map(self, map_id: str) -> ImportedMap:
        metadata = self._map_metadata(map_id)
        directory = self._uploads_root / map_id
        original = directory / str(metadata.get("original_filename", ""))
        transmission = directory / "normalized" / str(
            metadata.get("transmission_filename", "")
        )
        if (
            not original.is_file()
            or original.is_symlink()
            or not transmission.is_file()
            or transmission.is_symlink()
        ):
            raise ValidationError("stored map files are missing or unsafe")
        digest = sha256_file(transmission)
        if digest != metadata.get("sha256"):
            raise ValidationError("stored normalized map SHA-256 is invalid")
        return ImportedMap(
            original_path=original.resolve(),
            transmission_path=transmission.resolve(),
            image_format=str(metadata["image_format"]),
            original_width=int(metadata["original_width"]),
            original_height=int(metadata["original_height"]),
            width=int(metadata["width"]),
            height=int(metadata["height"]),
            file_size=transmission.stat().st_size,
            sha256=digest,
        )

    def create_mission(self, request: Mapping[str, Any]) -> dict[str, Any]:
        imported = self._imported_map(str(request["map_id"]))
        robot_start = Point.from_value(
            request.get("robot_start_image"), "robot_start_image"
        )
        has_explicit_scale = request.get("meters_per_pixel") is not None
        has_calibration = request.get("scale_calibration") is not None
        if has_explicit_scale == has_calibration:
            raise ValidationError(
                "provide exactly one of meters_per_pixel or scale_calibration"
            )
        if has_explicit_scale:
            meters_per_pixel = float(request["meters_per_pixel"])
        else:
            scale = request.get("scale_calibration")
            if not isinstance(scale, Mapping):
                raise ValidationError("scale_calibration is required")
            meters_per_pixel = calculate_scale(
                Point.from_value(scale.get("first"), "scale first"),
                Point.from_value(scale.get("second"), "scale second"),
                scale.get("real_distance_m"),
            )
        initial_yaw = float(request["initial_yaw"])
        transform = CoordinateTransform(
            image_origin=robot_start,
            meters_per_pixel=meters_per_pixel,
            rotation_radians=initial_yaw,
            invert_y=True,
            frame_id="mission_map",
        )
        mission_id = request.get("mission_id") or new_mission_id()
        mission_version = int(request.get("mission_version", 1))
        manifest = create_manifest(
            mission_name=str(request["mission_name"]),
            mission_id=mission_id,
            mission_version=mission_version,
            imported_map=imported,
            transform=transform,
            robot_start_image=robot_start,
            initial_yaw=initial_yaw,
            entrance_image_points=tuple(
                Point.from_value(value, "entrance")
                for value in request.get("entrances", [])
            ),
            available_teams=int(request.get("available_teams", 0)),
            available_rescuers=int(request.get("available_rescuers", 0)),
            notes=str(request.get("notes", "")),
        )
        manifest = MissionManifest.from_dict(
            {**manifest.to_dict(), "source_map_id": str(request["map_id"])}
        )
        with self._storage_lock:
            target = self.store.mission_dir(mission_id, mission_version)
            if target.exists():
                existing = self.store.load_manifest(mission_id, mission_version)
                candidate = manifest.to_dict()
                candidate["created_at"] = existing.created_at
                manifest = MissionManifest.from_dict(candidate)
            self.store.save_mission(
                manifest, imported.transmission_path, imported.original_path
            )
        with self._lock:
            self._active_mission = (
                manifest.mission_id,
                manifest.mission_version,
            )
        value = manifest.to_dict()
        self.events.publish("mission.created", value)
        return value

    def get_mission(self, mission_id: str, mission_version: int) -> dict[str, Any]:
        try:
            return self.store.load_manifest(mission_id, mission_version).to_dict()
        except ValidationError as error:
            path = self.store.mission_dir(mission_id, mission_version)
            if not path.is_dir():
                raise ResourceNotFoundError("mission version was not found") from error
            raise

    def activate_mission(
        self, mission_id: str, mission_version: int
    ) -> dict[str, Any]:
        manifest = self.get_mission(mission_id, mission_version)
        active = (str(manifest["mission_id"]), int(manifest["mission_version"]))
        with self._lock:
            self._active_mission = active
        value = {"mission_id": active[0], "mission_version": active[1]}
        self.events.publish("mission.activated", value)
        return value

    def list_missions(self) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        if not self.store.root.exists():
            return values
        for mission_root in sorted(self.store.root.iterdir()):
            if not mission_root.is_dir() or SAFE_ID_RE.fullmatch(mission_root.name) is None:
                continue
            for version in self.store.list_versions(mission_root.name):
                try:
                    values.append(self.get_mission(mission_root.name, version))
                except (HostAppError, OSError):
                    continue
        return values

    def mission_base_map_path(self, mission_id: str, mission_version: int) -> Path:
        manifest = MissionManifest.from_dict(
            self.get_mission(mission_id, mission_version)
        )
        path = self.store.mission_dir(mission_id, mission_version) / manifest.base_map.filename
        if not path.is_file() or path.is_symlink():
            raise ResourceNotFoundError("mission base map was not found")
        return path

    def _stage_or_existing(
        self, source: Path, kind: str, mission_id: str, version: int
    ) -> Path:
        with self._storage_lock:
            try:
                return self.spool.stage_outgoing(
                    source, kind, mission_id, version
                ).path
            except StaleVersionError:
                destination = (
                    self.spool.outgoing
                    / f"{mission_id}_{kind}_v{version}{source.suffix.lower()}"
                )
                if (
                    not destination.is_file()
                    or destination.is_symlink()
                    or sha256_file(destination) != sha256_file(source)
                ):
                    raise StaleVersionError(
                        f"{kind} v{version} is staged with different content"
                    )
                return destination

    def _new_operation(self, operation_type: str, subject: Mapping[str, Any]) -> str:
        operation_id = f"op-{uuid.uuid4().hex}"
        now = utc_now()
        value = {
            "operation_id": operation_id,
            "operation_type": operation_type,
            "state": "running",
            "created_at": now,
            "updated_at": now,
            "subject": copy.deepcopy(dict(subject)),
            "result": None,
            "error": None,
        }
        with self._lock:
            self._operations[operation_id] = value
        self.events.publish("operation.started", value)
        return operation_id

    def _operation_progress(self, operation_id: str, stage: str, feedback: Any) -> None:
        payload = {
            "operation_id": operation_id,
            "artifact": stage,
            **asdict(feedback),
        }
        self.events.publish("operation.progress", payload)

    def _finish_operation(self, operation_id: str, future: Future[Any]) -> None:
        try:
            result = future.result()
            value = asdict(result)
            state = "succeeded" if bool(value.get("success")) else "failed"
            error = (
                getattr(result, "error_message", "")
                or value.get("error_message")
                or None
            )
        except Exception as caught:
            value = None
            state = "failed"
            error = str(caught)
        with self._lock:
            operation = self._operations[operation_id]
            operation.update(
                state=state,
                updated_at=utc_now(),
                result=value,
                error=error,
            )
            event_value = copy.deepcopy(operation)
        self.events.publish("operation.completed", event_value)

    def get_operation(self, operation_id: str) -> dict[str, Any]:
        self._safe_identifier(operation_id, "operation_id")
        with self._lock:
            value = self._operations.get(operation_id)
            if value is None:
                raise ResourceNotFoundError("operation was not found")
            return copy.deepcopy(value)

    def send_mission(self, mission_id: str, mission_version: int) -> dict[str, Any]:
        manifest = MissionManifest.from_dict(
            self.get_mission(mission_id, mission_version)
        )
        directory = self.store.mission_dir(mission_id, mission_version)
        base_map = self._stage_or_existing(
            directory / manifest.base_map.filename,
            "base_map",
            mission_id,
            mission_version,
        )
        manifest_path = self._stage_or_existing(
            directory / "mission_manifest.json",
            "mission_manifest",
            mission_id,
            mission_version,
        )
        with self._lock:
            self._active_mission = (mission_id, mission_version)
        operation_id = self._new_operation(
            "mission.send",
            {"mission_id": mission_id, "mission_version": mission_version},
        )
        future = self.workflow.send_initial_mission(
            manifest,
            base_map,
            manifest_path,
            lambda stage, feedback: self._operation_progress(
                operation_id, stage, feedback
            ),
        )
        future.add_done_callback(
            lambda completed: self._finish_operation(operation_id, completed)
        )
        return self.get_operation(operation_id)

    def _result_path(
        self, mission_id: str, mission_version: int, result_version: int
    ) -> Path:
        path = (
            self.store.mission_dir(mission_id, mission_version)
            / "results"
            / f"semantic_result_v{int(result_version)}.json"
        )
        if not path.is_file() or path.is_symlink():
            raise ResourceNotFoundError("semantic result was not found")
        return path

    def list_results(self, mission_id: str, mission_version: int) -> list[dict[str, Any]]:
        self.get_mission(mission_id, mission_version)
        directory = self.store.mission_dir(mission_id, mission_version) / "results"
        values = []
        if directory.is_dir():
            candidates = []
            for path in directory.iterdir():
                match = RESULT_FILE_RE.fullmatch(path.name)
                if match and path.is_file() and not path.is_symlink():
                    candidates.append((int(match.group(1)), path))
            for _, path in sorted(candidates):
                semantic = SemanticResult(self.store.load_json(path))
                if (
                    semantic.mission_id == mission_id
                    and int(semantic.to_dict()["base_map_version"])
                    == mission_version
                ):
                    values.append(semantic.to_dict())
        return values

    def get_result(
        self, mission_id: str, mission_version: int, result_version: int
    ) -> dict[str, Any]:
        semantic = SemanticResult(
            self.store.load_json(
                self._result_path(mission_id, mission_version, result_version)
            )
        )
        value = semantic.to_dict()
        if semantic.mission_id != mission_id or value["base_map_version"] != mission_version:
            raise ValidationError("semantic result does not belong to this mission version")
        if semantic.result_version != int(result_version):
            raise ValidationError("semantic result path and version do not match")
        return value

    def load_result(
        self, mission_id: str, mission_version: int, result_version: int
    ) -> dict[str, Any]:
        semantic = SemanticResult(
            self.get_result(mission_id, mission_version, result_version)
        )
        key = (mission_id, int(mission_version), int(result_version))
        with self._lock:
            if key not in self._reviews:
                self._reviews[key] = ReviewSession(semantic)
                self._review_revisions[key] = 0
            self._active_mission = (mission_id, int(mission_version))
        value = self.review_state(*key)
        self.events.publish(
            "result.loaded",
            {
                "mission_id": mission_id,
                "mission_version": mission_version,
                "result_version": result_version,
            },
        )
        return value

    def _review(
        self, mission_id: str, mission_version: int, result_version: int
    ) -> ReviewSession:
        key = (mission_id, int(mission_version), int(result_version))
        with self._lock:
            review = self._reviews.get(key)
        if review is None:
            raise ResourceNotFoundError("review is not loaded")
        return review

    def review_state(
        self, mission_id: str, mission_version: int, result_version: int
    ) -> dict[str, Any]:
        review = self._review(mission_id, mission_version, result_version)
        key = (mission_id, int(mission_version), int(result_version))
        with self._lock:
            return {
                "mission_id": mission_id,
                "mission_version": int(mission_version),
                "result_version": int(result_version),
                "revision": self._review_revisions[key],
                "original_semantic_result": review.original_result,
                "reviewed_result": review.reviewed_result,
                "host_edits": review.host_edits,
                "can_undo": review.can_undo,
                "can_redo": review.can_redo,
                "final_approved": review.final_approved,
            }

    @staticmethod
    def _required(arguments: Mapping[str, Any], name: str) -> Any:
        if name not in arguments:
            raise ValidationError(f"review command requires {name}")
        return arguments[name]

    def apply_review_command(
        self,
        mission_id: str,
        mission_version: int,
        result_version: int,
        command: str,
        arguments: Mapping[str, Any],
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        review = self._review(mission_id, mission_version, result_version)
        key = (mission_id, int(mission_version), int(result_version))
        value = dict(arguments)
        required = lambda name: self._required(value, name)
        with self._lock:
            current_revision = self._review_revisions[key]
            if (
                expected_revision is not None
                and int(expected_revision) != current_revision
            ):
                raise StaleVersionError(
                    "review revision changed; reload before applying this command"
                )
            if command == "set_victim_status":
                review.set_victim_status(required("victim_id"), required("status"))
            elif command == "set_victim_priority":
                review.set_victim_priority(required("victim_id"), required("priority"))
            elif command == "set_victim_position":
                review.set_victim_position(
                    required("victim_id"), required("x"), required("y")
                )
            elif command == "set_route_approved":
                review.set_route_approved(required("route_id"), required("approved"))
            elif command == "modify_risk_zone":
                review.modify_risk_zone(required("risk_id"), required("risk_zone"))
            elif command == "clear_risk_zone":
                review.clear_risk_zone(required("risk_id"))
            elif command == "add_risk_zone":
                review.add_risk_zone(required("risk_zone"))
            elif command == "remove_added_risk_zone":
                review.remove_added_risk_zone(required("risk_id"))
            elif command == "update_added_risk_zone":
                review.update_added_risk_zone(
                    required("risk_id"), required("risk_zone")
                )
            elif command == "set_team_assignments":
                review.set_team_assignments(required("assignments"))
            elif command == "upsert_team_assignment":
                review.upsert_team_assignment(required("assignment"))
            elif command == "remove_team_assignment":
                review.remove_team_assignment(required("team_id"))
            elif command == "set_safe_waiting_points":
                review.set_safe_waiting_points(required("points"))
            elif command == "add_safe_waiting_point":
                review.add_safe_waiting_point(
                    required("waiting_id"), required("x"), required("y")
                )
            elif command == "update_safe_waiting_point":
                review.update_safe_waiting_point(
                    required("waiting_id"), required("x"), required("y")
                )
            elif command == "remove_safe_waiting_point":
                review.remove_safe_waiting_point(required("waiting_id"))
            elif command == "set_notes":
                review.set_notes(required("notes"))
            elif command == "undo":
                if not review.undo():
                    raise ValidationError("there is no review edit to undo")
            elif command == "redo":
                if not review.redo():
                    raise ValidationError("there is no review edit to redo")
            else:
                raise ValidationError("unsupported review command")
            self._review_revisions[key] = current_revision + 1
        state = self.review_state(mission_id, mission_version, result_version)
        self.events.publish(
            "review.changed",
            {
                "mission_id": mission_id,
                "mission_version": mission_version,
                "result_version": result_version,
                "command": command,
                "revision": state["revision"],
            },
        )
        return state

    def build_approved_plan(
        self,
        mission_id: str,
        mission_version: int,
        result_version: int,
        plan_version: int,
        modified_at: str | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        review = self._review(mission_id, mission_version, result_version)
        key = (mission_id, int(mission_version), int(result_version))
        with self._lock:
            if (
                expected_revision is not None
                and int(expected_revision) != self._review_revisions[key]
            ):
                raise StaleVersionError(
                    "review revision changed; reload before building the plan"
                )
            current = review.final_approved
            if current and current.get("approved_plan_version") == int(plan_version):
                plan = ApprovedPlan.from_dict(
                    current,
                    expected_mission_id=mission_id,
                    expected_mission_version=int(mission_version),
                    expected_result_version=int(result_version),
                )
            else:
                plan = review.build_approved_plan(int(plan_version), modified_at)
        with self._storage_lock:
            self.store.save_approved_plan(plan, int(mission_version))
        value = plan.to_dict()
        self.events.publish("approved_plan.built", value)
        return value

    def _plan_path(
        self, mission_id: str, mission_version: int, plan_version: int
    ) -> Path:
        path = (
            self.store.mission_dir(mission_id, mission_version)
            / "plans"
            / f"approved_plan_v{int(plan_version)}.json"
        )
        if not path.is_file() or path.is_symlink():
            raise ResourceNotFoundError("approved plan was not found")
        return path

    def _stored_approved_plans(
        self, mission_id: str, mission_version: int
    ) -> list[ApprovedPlan]:
        mission_version = positive_int(mission_version, "mission_version")
        self.get_mission(mission_id, mission_version)
        directory = self.store.mission_dir(mission_id, mission_version) / "plans"
        if not directory.is_dir() or directory.is_symlink():
            return []
        candidates: list[tuple[int, Path]] = []
        for path in directory.iterdir():
            match = PLAN_FILE_RE.fullmatch(path.name)
            if match and path.is_file() and not path.is_symlink():
                candidates.append((int(match.group(1)), path))
        plans: list[ApprovedPlan] = []
        for file_version, path in sorted(candidates):
            plan = ApprovedPlan.from_dict(
                self.store.load_json(path),
                expected_mission_id=mission_id,
                expected_mission_version=mission_version,
            )
            if plan.approved_plan_version != file_version:
                raise ValidationError(
                    "approved plan path and version do not match"
                )
            plans.append(plan)
        return plans

    def list_approved_plans(
        self, mission_id: str, mission_version: int, result_version: int
    ) -> dict[str, Any]:
        result_version = positive_int(result_version, "result_version")
        self.get_result(mission_id, mission_version, result_version)
        with self._storage_lock:
            plans = self._stored_approved_plans(mission_id, mission_version)
        items = [
            plan.to_dict()
            for plan in plans
            if plan.base_result_version == result_version
        ]
        return {
            "items": items,
            "latest_plan_version": (
                plans[-1].approved_plan_version if plans else 0
            ),
        }

    def current_approved_plan(
        self, mission_id: str, mission_version: int, result_version: int
    ) -> dict[str, Any]:
        catalog = self.list_approved_plans(
            mission_id, mission_version, result_version
        )
        items = catalog["items"]
        if not items:
            raise ResourceNotFoundError("approved plan was not found")
        return copy.deepcopy(items[-1])

    def send_approved_plan(
        self,
        mission_id: str,
        mission_version: int,
        result_version: int,
        plan_version: int,
    ) -> dict[str, Any]:
        source = self._plan_path(mission_id, mission_version, plan_version)
        plan = ApprovedPlan.from_dict(
            self.store.load_json(source),
            expected_mission_id=mission_id,
            expected_mission_version=int(mission_version),
            expected_result_version=int(result_version),
        )
        staged = self._stage_or_existing(
            source, "approved_plan", mission_id, int(plan_version)
        )
        with self._lock:
            self._active_mission = (mission_id, int(mission_version))
        operation_id = self._new_operation(
            "approved_plan.send",
            {
                "mission_id": mission_id,
                "mission_version": mission_version,
                "result_version": result_version,
                "plan_version": plan_version,
            },
        )
        future = self.workflow.send_approved_plan(
            plan,
            staged,
            lambda stage, feedback: self._operation_progress(
                operation_id, stage, feedback
            ),
        )
        future.add_done_callback(
            lambda completed: self._finish_operation(operation_id, completed)
        )
        return self.get_operation(operation_id)

    def list_previews(self, mission_id: str, mission_version: int) -> list[int]:
        self.get_mission(mission_id, mission_version)
        directory = self.store.mission_dir(mission_id, mission_version) / "previews"
        versions = []
        if directory.is_dir():
            for path in directory.iterdir():
                match = PREVIEW_FILE_RE.fullmatch(path.name)
                if match and path.is_file() and not path.is_symlink():
                    versions.append(int(match.group(1)))
        return sorted(versions)

    def preview_path(
        self, mission_id: str, mission_version: int, preview_version: int
    ) -> Path:
        path = (
            self.store.mission_dir(mission_id, mission_version)
            / "previews"
            / f"map_preview_v{int(preview_version)}.png"
        )
        if not path.is_file() or path.is_symlink():
            raise ResourceNotFoundError("map preview was not found")
        return path

    def preview_metadata(
        self, mission_id: str, mission_version: int, preview_version: int
    ) -> dict[str, Any]:
        metadata = read_map_preview_metadata(
            self.preview_path(mission_id, mission_version, preview_version)
        )
        if metadata.mission_id != mission_id:
            raise ValidationError("map preview mission_id does not match its path")
        if metadata.base_map_version != int(mission_version):
            raise ValidationError("map preview base_map_version does not match its path")
        if metadata.artifact_version != int(preview_version):
            raise ValidationError("map preview artifact_version does not match its path")
        return asdict(metadata)

    def _apply_received_semantic(self, semantic: SemanticResult, notice: Any) -> bool:
        with self._lock:
            active = self._active_mission
        if active is None:
            raise ValidationError("there is no active mission for semantic result")
        mission_id, mission_version = active
        if semantic.mission_id != mission_id:
            raise ValidationError("semantic result mission_id differs from active mission")
        if int(semantic.to_dict()["base_map_version"]) != mission_version:
            raise ValidationError("semantic result base_map_version is stale")
        stored_new = True
        with self._storage_lock:
            try:
                self.store.save_semantic_result(semantic, mission_version)
            except StaleVersionError:
                stored_new = False
                existing = self.store.load_json(
                    self._result_path(
                        mission_id, mission_version, semantic.result_version
                    )
                )
                if existing != semantic.to_dict():
                    raise
        key = (mission_id, mission_version, semantic.result_version)
        with self._lock:
            if stored_new or key not in self._reviews:
                self._reviews[key] = ReviewSession(semantic)
                self._review_revisions[key] = 0
        self.events.publish(
            "result.received" if stored_new else "result.duplicate_received",
            {
                "mission_id": mission_id,
                "mission_version": mission_version,
                "result_version": semantic.result_version,
                "transfer_id": notice.transfer_id,
            },
        )
        return True

    def _apply_received_preview(self, path: Path, notice: Any) -> bool:
        with self._lock:
            active = self._active_mission
        if active is None or active[0] != notice.mission_id:
            raise ValidationError("map preview does not belong to the active mission")
        with self._storage_lock:
            stored = self.store.save_map_preview(
                active[0],
                active[1],
                notice.artifact_version,
                path,
                notice.sha256,
            )
        self.events.publish(
            "preview.received",
            {
                "mission_id": active[0],
                "mission_version": active[1],
                "preview_version": notice.artifact_version,
                "transfer_id": notice.transfer_id,
                "file_size": stored.stat().st_size,
            },
        )
        return True

    def _on_received_error(self, message: str, notice: Any) -> None:
        self.events.publish(
            "artifact.rejected",
            {
                "transfer_id": notice.transfer_id,
                "artifact_kind": notice.artifact_kind,
                "mission_id": notice.mission_id,
                "artifact_version": notice.artifact_version,
                "error": message,
            },
        )

    def status(self) -> dict[str, Any]:
        with self._lock:
            active = self._active_mission
            operation_counts: dict[str, int] = {}
            for operation in self._operations.values():
                state = str(operation["state"])
                operation_counts[state] = operation_counts.get(state, 0) + 1
        return {
            "bridge": self._bridge_status_value(self.bridge.status()),
            "active_mission": (
                {"mission_id": active[0], "mission_version": active[1]}
                if active
                else None
            ),
            "operations": operation_counts,
        }

    def health(self) -> dict[str, Any]:
        status = self.status()
        return {
            "ok": True,
            "service": "ai-rescue-box-host-api",
            "schema_version": "1.0",
            "bridge_state": status["bridge"]["state"],
        }

    def reconnect_bridge(self) -> bool:
        return bool(self.bridge.reconnect().result(timeout=5.0))

    def close(self) -> None:
        self.loader.close()
        self.bridge.remove_status_listener(self._on_bridge_status)
        if self._owns_bridge:
            self.bridge.close()


__all__ = ["HostApiService", "ResourceNotFoundError"]
