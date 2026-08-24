"""Business-plan alignment for inbound Tablet Missions and return-route review."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import shutil
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..errors import StaleVersionError, ValidationError
from ..mission.models import MissionManifest
from ..mission.review import ApprovedPlan, ReviewSession
from ..storage.atomic import atomic_copy, atomic_write_json
from .service import HostApiService
from ..mission.workflow import ReceivedArtifactLoader

_INSTALLED = False
_MISSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_received_file(loader: ReceivedArtifactLoader, notice: Any) -> Path:
    path = Path(notice.local_path).expanduser()
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise ValidationError("Bridge가 전달한 Mission artifact 경로가 안전하지 않습니다.")
    size = path.stat().st_size
    if size < 1 or size > loader.max_file_bytes or size != int(notice.file_size):
        raise ValidationError("수신 Mission artifact 크기가 metadata와 다릅니다.")
    if _sha(path) != str(notice.sha256):
        raise ValidationError("수신 Mission artifact SHA-256이 metadata와 다릅니다.")
    if not _MISSION_ID.fullmatch(str(notice.mission_id)):
        raise ValidationError("수신 Mission ID 형식이 올바르지 않습니다.")
    if int(notice.artifact_version) < 1:
        raise ValidationError("수신 Mission Version은 1 이상이어야 합니다.")
    return path


def _owner(loader: ReceivedArtifactLoader) -> Any:
    owner = loader._review_owner(loader.on_semantic_result)
    if owner is None or not hasattr(owner, "store") or not hasattr(owner, "data_root"):
        raise ValidationError("Host Mission 자동 등록 서비스가 준비되지 않았습니다.")
    return owner


def _stage_root(owner: Any, mission_id: str, version: int) -> Path:
    root = Path(owner.data_root) / "incoming_missions" / mission_id / f"v{version}"
    if root.is_symlink():
        raise ValidationError("Host Mission staging 경로가 안전하지 않습니다.")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _copy_idempotent(source: Path, destination: Path, expected_sha: str) -> None:
    if destination.exists():
        if destination.is_symlink() or not destination.is_file() or _sha(destination) != expected_sha:
            raise StaleVersionError("동일 Mission Version staging 파일의 내용이 다릅니다.")
        return
    atomic_copy(source, destination)
    if _sha(destination) != expected_sha:
        raise ValidationError("Mission staging SHA 검증에 실패했습니다.")


def _load_staged_manifest(path: Path) -> MissionManifest:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValidationError(f"mission_manifest를 읽을 수 없습니다: {error}") from error
    return MissionManifest.from_dict(raw)


def _finish_registration(owner: Any, notice: Any, stage: Path) -> tuple[bool, Path | None]:
    manifest_path = stage / "mission_manifest.json"
    base_path = stage / "base_map.received"
    if not manifest_path.is_file() or not base_path.is_file():
        return False, None
    manifest = _load_staged_manifest(manifest_path)
    if manifest.mission_id != str(notice.mission_id) or manifest.mission_version != int(notice.artifact_version):
        raise ValidationError("수신 Mission manifest identity/version이 UWB metadata와 다릅니다.")
    if _sha(base_path) != manifest.base_map.sha256:
        raise ValidationError("수신 구조도 SHA-256이 Mission Manifest와 다릅니다.")

    target = owner.store.mission_dir(manifest.mission_id, manifest.mission_version)
    existed = target.exists()
    if not existed:
        target = owner.store.save_mission(manifest, base_path)
    else:
        stored_manifest = target / "mission_manifest.json"
        stored_map = target / manifest.base_map.filename
        if stored_manifest.is_file() and owner.store.load_json(stored_manifest) != manifest.to_dict():
            raise StaleVersionError("이미 받은 Mission Version의 manifest 내용이 다릅니다.")
        if not stored_manifest.exists():
            atomic_write_json(stored_manifest, manifest.to_dict())
        if stored_map.exists():
            if stored_map.is_symlink() or _sha(stored_map) != manifest.base_map.sha256:
                raise StaleVersionError("이미 받은 Mission Version의 구조도 내용이 다릅니다.")
        else:
            atomic_copy(base_path, stored_map)
    shutil.rmtree(stage, ignore_errors=True)
    events = getattr(owner, "events", None)
    if events is not None:
        events.publish(
            "mission.duplicate_received" if existed else "mission.received",
            {
                "mission_id": manifest.mission_id,
                "mission_version": manifest.mission_version,
                "source": "tablet_via_jetson_uwb",
                "sha256": manifest.base_map.sha256,
            },
        )
    return True, target


def _receive_mission_piece(loader: ReceivedArtifactLoader, notice: Any) -> None:
    source = _safe_received_file(loader, notice)
    owner = _owner(loader)
    mission_id = str(notice.mission_id)
    version = int(notice.artifact_version)
    stage = _stage_root(owner, mission_id, version)
    with owner._storage_lock:
        if notice.artifact_kind == "base_map":
            _copy_idempotent(source, stage / "base_map.received", str(notice.sha256))
        elif notice.artifact_kind == "mission_manifest":
            try:
                raw = json.loads(source.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValidationError(f"mission_manifest JSON 오류: {error}") from error
            manifest = MissionManifest.from_dict(raw)
            if manifest.mission_id != mission_id or manifest.mission_version != version:
                raise ValidationError("mission_manifest identity/version이 UWB metadata와 다릅니다.")
            canonical = json.dumps(
                manifest.to_dict(), ensure_ascii=False, sort_keys=True, indent=2
            ).encode("utf-8")
            destination = stage / "mission_manifest.json"
            if destination.exists():
                if destination.is_symlink() or destination.read_bytes() != canonical:
                    raise StaleVersionError("동일 Mission Version manifest가 이미 다른 내용으로 staging 되었습니다.")
            else:
                part = destination.with_name(f".{destination.name}.{os.getpid()}.part")
                part.write_bytes(canonical)
                os.replace(part, destination)
        else:
            raise ValidationError("Mission artifact 종류가 올바르지 않습니다.")
        _finish_registration(owner, notice, stage)


def _route_identifier(item: Mapping[str, Any]) -> str | None:
    for key in ("route_id", "id"):
        value = item.get(key)
        if value not in {None, ""}:
            return str(value)
    return None


def _point(value: Any, name: str) -> dict[str, float]:
    if not isinstance(value, Mapping):
        raise ValidationError(f"{name} must be an object")
    x, y = value.get("x"), value.get("y")
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        raise ValidationError(f"{name} requires numeric x/y")
    return {"x": float(x), "y": float(y)}


def _validate_route(value: Mapping[str, Any], route_id: str) -> dict[str, Any]:
    route = copy.deepcopy(dict(value))
    route["route_id"] = route_id
    points = route.get("points")
    if not isinstance(points, Sequence) or isinstance(points, (str, bytes)) or len(points) < 2:
        raise ValidationError("route modification requires at least two points")
    route["points"] = [_point(item, "route point") for item in points]
    route["total_distance"] = sum(
        math.hypot(second["x"] - first["x"], second["y"] - first["y"])
        for first, second in zip(route["points"], route["points"][1:])
    )
    route["start"] = _point(route.get("start", route["points"][0]), "route start")
    route["goal"] = _point(route.get("goal", route["points"][-1]), "route goal")
    route.setdefault("goal_type", "entrance")
    route["host_status"] = "modified"
    route["source"] = "host_user"
    return route


def install_business_plan_extensions() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    original_conflicts = ReceivedArtifactLoader._review_conflicts

    @staticmethod
    def review_conflicts(semantic: Mapping[str, Any], edits: Mapping[str, Any]) -> list[Mapping[str, str]]:
        conflicts = list(original_conflicts(semantic, edits))
        route_ids = {
            str(item.get("route_id", item.get("id")))
            for layer in ("entry_routes", "return_routes")
            for item in semantic.get(layer, [])
            if isinstance(item, Mapping)
            and item.get("route_id", item.get("id")) not in {None, ""}
        }
        known = {(item.get("kind"), item.get("id")) for item in conflicts}
        for edit_key in ("route_approvals", "route_modifications"):
            values = edits.get(edit_key, {})
            if isinstance(values, Mapping):
                for identity in values:
                    marker = (
                        "route_approval" if edit_key == "route_approvals" else "route_modification",
                        str(identity),
                    )
                    if str(identity) not in route_ids and marker not in known:
                        conflicts.append({"kind": marker[0], "id": marker[1]})
        return [
            item
            for item in conflicts
            if not (item.get("kind") == "route_approval" and item.get("id") in route_ids)
        ]

    ReceivedArtifactLoader._review_conflicts = review_conflicts

    original_load = ReceivedArtifactLoader._load

    def load(self: ReceivedArtifactLoader, notice: Any) -> None:
        if notice.artifact_kind not in {"base_map", "mission_manifest"}:
            return original_load(self, notice)
        try:
            _receive_mission_piece(self, notice)
        except Exception as error:
            try:
                self._send_application_ack(notice.transfer_id, False, str(error))
            except Exception as ack_error:
                error = ValidationError(f"{error}; application NACK 전달 실패: {ack_error}")
            if self.on_error is not None:
                self.on_error(str(error), notice)
            return
        try:
            self._send_application_ack(notice.transfer_id, True, "")
        except Exception as error:
            if self.on_error is not None:
                self.on_error(f"application ACK 전달 실패: {error}", notice)

    ReceivedArtifactLoader._load = load  # type: ignore[assignment]

    original_review_init = ReviewSession.__init__

    def review_init(self: ReviewSession, *args: Any, **kwargs: Any) -> None:
        original_review_init(self, *args, **kwargs)
        self._recommendations["return_routes"] = copy.deepcopy(
            self._original.get("return_routes", [])
        )
        self._edits.setdefault("route_modifications", {})

    ReviewSession.__init__ = review_init  # type: ignore[assignment]

    def modify_route(self: ReviewSession, route_id: str, route_patch: Mapping[str, Any]) -> None:
        route_id = str(route_id)
        original = None
        for layer in ("entry_routes", "return_routes"):
            for item in self._original.get(layer, []):
                if _route_identifier(item) == route_id:
                    original = copy.deepcopy(dict(item))
                    break
            if original is not None:
                break
        if original is None:
            raise ValidationError("route was not found")
        original.update(copy.deepcopy(dict(route_patch)))
        replacement = _validate_route(original, route_id)
        self._before_edit()
        self._edits.setdefault("route_modifications", {})[route_id] = replacement

    ReviewSession.modify_route = modify_route  # type: ignore[attr-defined]

    original_reviewed_getter = ReviewSession.reviewed_result.fget
    assert original_reviewed_getter is not None

    def reviewed_result(self: ReviewSession) -> dict[str, Any]:
        result = original_reviewed_getter(self)
        modifications = self._edits.get("route_modifications", {})
        approvals = self._edits.get("route_approvals", {})
        for layer in ("entry_routes", "return_routes"):
            reviewed = []
            for item in result.get(layer, []):
                route_id = _route_identifier(item)
                route = copy.deepcopy(modifications.get(route_id, item))
                if route_id in approvals:
                    route["host_status"] = "approved" if approvals[route_id] else "excluded"
                reviewed.append(route)
            result[layer] = reviewed
        return result

    ReviewSession.reviewed_result = property(reviewed_result)  # type: ignore[assignment]

    original_build = ReviewSession.build_approved_plan

    def build_approved_plan(self: ReviewSession, plan_version: int, modified_at: str | None = None) -> ApprovedPlan:
        base = original_build(self, plan_version, modified_at)
        modifications = self._edits.get("route_modifications", {})
        approvals = self._edits.get("route_approvals", {})

        def approved(layer: str) -> list[Mapping[str, Any]]:
            values = []
            for item in self._original.get(layer, []):
                route_id = _route_identifier(item)
                if not approvals.get(route_id, False):
                    continue
                route = copy.deepcopy(modifications.get(route_id, item))
                route["host_status"] = "approved"
                values.append(route)
            return values

        entry = approved("entry_routes")
        returning = approved("return_routes")
        data = base.to_dict()
        data["approved_entry_routes"] = entry
        data["approved_return_routes"] = returning
        data["approved_routes"] = [*entry, *returning]
        plan = ApprovedPlan.from_dict(data)
        self._final_approved = plan.to_dict()
        return plan

    ReviewSession.build_approved_plan = build_approved_plan  # type: ignore[assignment]

    original_command = HostApiService.apply_review_command

    def apply_review_command(
        self: HostApiService,
        mission_id: str,
        mission_version: int,
        result_version: int,
        command: str,
        arguments: Mapping[str, Any],
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        if command != "modify_route":
            return original_command(
                self,
                mission_id,
                mission_version,
                result_version,
                command,
                arguments,
                expected_revision,
            )
        review = self._review(mission_id, mission_version, result_version)
        key = (mission_id, int(mission_version), int(result_version))
        with self._lock:
            current_revision = self._review_revisions[key]
            if expected_revision is not None and int(expected_revision) != current_revision:
                raise StaleVersionError(
                    "review revision changed; reload before applying this command"
                )
            if "route_id" not in arguments or "route" not in arguments:
                raise ValidationError("modify_route requires route_id and route")
            review.modify_route(str(arguments["route_id"]), arguments["route"])
            self._review_revisions[key] = current_revision + 1
        state = self.review_state(mission_id, mission_version, result_version)
        self.events.publish(
            "review.changed",
            {
                "mission_id": mission_id,
                "mission_version": int(mission_version),
                "result_version": int(result_version),
                "revision": state["revision"],
                "command": command,
            },
        )
        return state

    HostApiService.apply_review_command = apply_review_command  # type: ignore[assignment]
