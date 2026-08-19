"""Apply verified mission artifacts without overwriting prior versions."""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from PIL import Image, UnidentifiedImageError

from ..domain import MissionManifest, StaleVersionError, ValidationError, utc_now
from ..storage import atomic_copy, atomic_write_json, sha256_file
from .artifacts import validate_approved_plan, validate_semantic_result


VERSION_DIR_RE = re.compile(r"v([1-9][0-9]*)\Z")
RESULT_RE = re.compile(r"semantic_result_v([1-9][0-9]*)\.json\Z")
PLAN_RE = re.compile(r"approved_plan_v([1-9][0-9]*)\.json\Z")
CURRENT_MISSION_FILE = "current_mission.json"


@dataclass(frozen=True)
class AppliedMission:
    manifest: MissionManifest
    directory: Path
    base_map_path: Path
    manifest_path: Path
    verification_path: Path


class MissionManager:
    """Version-aware mission repository rooted at ``data/missions``."""

    def __init__(
        self,
        root: Path,
        *,
        max_map_bytes: int = 10 * 1024 * 1024,
        max_json_bytes: int = 2 * 1024 * 1024,
    ) -> None:
        self.root = Path(root)
        self.max_map_bytes = max_map_bytes
        self.max_json_bytes = max_json_bytes
        self._lock = threading.RLock()

    def _read_json(self, path: Path) -> Mapping[str, Any]:
        path = Path(path)
        if path.is_symlink() or not path.is_file():
            raise ValidationError("artifact JSON must be a regular non-symlink file")
        if not 0 < path.stat().st_size <= self.max_json_bytes:
            raise ValidationError("artifact JSON size is outside the allowed range")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValidationError(f"could not read artifact JSON: {error}") from error
        if not isinstance(value, Mapping):
            raise ValidationError("artifact JSON root must be an object")
        return value

    def _mission_root(self, mission_id: str) -> Path:
        return self.root / mission_id

    def mission_directory(self, mission_id: str, version: int) -> Path:
        return self._mission_root(mission_id) / f"v{version}"

    def latest_mission_version(self, mission_id: str) -> int | None:
        mission_root = self._mission_root(mission_id)
        if not mission_root.is_dir():
            return None
        versions = []
        for child in mission_root.iterdir():
            match = VERSION_DIR_RE.fullmatch(child.name)
            if child.is_dir() and match:
                versions.append(int(match.group(1)))
        return max(versions, default=None)

    def list_missions(self) -> tuple[tuple[str, int], ...]:
        if not self.root.is_dir():
            return ()
        result = []
        for mission_root in self.root.iterdir():
            if not mission_root.is_dir() or mission_root.is_symlink():
                continue
            try:
                children = tuple(mission_root.iterdir())
            except OSError:
                continue
            for child in children:
                match = VERSION_DIR_RE.fullmatch(child.name)
                if child.is_dir() and not child.is_symlink() and match:
                    result.append((mission_root.name, int(match.group(1))))
        return tuple(sorted(result, key=lambda item: (item[0], item[1])))

    def _current_path(self) -> Path:
        return self.root / CURRENT_MISSION_FILE

    def set_current_mission(self, mission_id: str, version: int) -> tuple[str, int]:
        applied = self.load_mission(mission_id, int(version))
        value = (applied.manifest.mission_id, applied.manifest.mission_version)
        self.root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            self._current_path(),
            {"mission_id": value[0], "mission_version": value[1], "state": "READY"},
        )
        return value

    def current_mission_ref(self) -> tuple[str, int] | None:
        path = self._current_path()
        if not path.exists():
            return None
        value = self._read_json(path)
        mission_id = value.get("mission_id")
        mission_version = value.get("mission_version")
        if not isinstance(mission_id, str) or not mission_id:
            raise ValidationError("current mission reference has invalid mission_id")
        if isinstance(mission_version, bool) or not isinstance(mission_version, int) or mission_version < 1:
            raise ValidationError("current mission reference has invalid mission_version")
        applied = self.load_mission(mission_id, mission_version)
        return applied.manifest.mission_id, applied.manifest.mission_version

    def _validate_base_map(self, path: Path, manifest: MissionManifest) -> str:
        path = Path(path)
        if path.is_symlink() or not path.is_file():
            raise ValidationError("base map must be a regular non-symlink file")
        size = path.stat().st_size
        if not 0 < size <= self.max_map_bytes:
            raise ValidationError("base map size is outside the allowed range")
        digest = sha256_file(path)
        if digest != manifest.base_map_sha256:
            raise ValidationError("base map SHA-256 does not match mission manifest")
        try:
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                width, height = image.size
                image_format = image.format
        except (OSError, UnidentifiedImageError) as error:
            raise ValidationError("base map is not a valid JPEG or PNG image") from error
        if image_format not in {"JPEG", "PNG"}:
            raise ValidationError("base map is not a JPEG or PNG image")
        if (width, height) != (manifest.base_map_width, manifest.base_map_height):
            raise ValidationError("base map dimensions do not match mission manifest")
        expected = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG"}[
            Path(manifest.base_map_filename).suffix.lower()
        ]
        if image_format != expected:
            raise ValidationError("base map content does not match its filename extension")
        return image_format

    def apply_mission(self, manifest_path: Path, base_map_path: Path) -> AppliedMission:
        manifest_source = Path(manifest_path)
        base_map_source = Path(base_map_path)
        manifest = MissionManifest.from_dict(self._read_json(manifest_source))
        image_format = self._validate_base_map(base_map_source, manifest)
        with self._lock:
            latest = self.latest_mission_version(manifest.mission_id)
            if latest is not None and manifest.mission_version <= latest:
                raise StaleVersionError(
                    f"mission version {manifest.mission_version} is not newer than {latest}"
                )
            mission_root = self._mission_root(manifest.mission_id)
            mission_root.mkdir(parents=True, exist_ok=True)
            destination = self.mission_directory(manifest.mission_id, manifest.mission_version)
            if destination.exists():
                raise StaleVersionError("mission version already exists")
            staging = mission_root / f".v{manifest.mission_version}.{uuid.uuid4().hex}.part"
            staging.mkdir()
            promoted = False
            try:
                extension = ".jpg" if image_format == "JPEG" else ".png"
                stored_map = staging / f"base_map{extension}"
                atomic_copy(base_map_source, stored_map, self.max_map_bytes)
                stored_manifest = staging / "mission_manifest.json"
                atomic_write_json(stored_manifest, manifest.to_dict())
                verification = {
                    "verified_at": utc_now(),
                    "mission_id": manifest.mission_id,
                    "mission_version": manifest.mission_version,
                    "base_map_sha256": sha256_file(stored_map),
                    "base_map_size": stored_map.stat().st_size,
                    "image_format": image_format,
                    "image_width": manifest.base_map_width,
                    "image_height": manifest.base_map_height,
                    "status": "verified",
                    "source_manifest_sha256": sha256_file(manifest_source),
                }
                verification_path = staging / "verification.json"
                atomic_write_json(verification_path, verification)
                os.replace(staging, destination)
                promoted = True
                atomic_write_json(
                    self._current_path(),
                    {
                        "mission_id": manifest.mission_id,
                        "mission_version": manifest.mission_version,
                        "state": "READY",
                    },
                )
            except Exception:
                shutil.rmtree(staging, ignore_errors=True)
                if promoted:
                    shutil.rmtree(destination, ignore_errors=True)
                raise
        return AppliedMission(
            manifest=manifest,
            directory=destination,
            base_map_path=destination / stored_map.name,
            manifest_path=destination / stored_manifest.name,
            verification_path=destination / verification_path.name,
        )

    def load_mission(self, mission_id: str, version: int | None = None) -> AppliedMission:
        if version is None:
            version = self.latest_mission_version(mission_id)
        if version is None:
            raise ValidationError("mission is not stored")
        directory = self.mission_directory(mission_id, version)
        manifest_path = directory / "mission_manifest.json"
        manifest = MissionManifest.from_dict(self._read_json(manifest_path))
        maps = [path for path in (directory / "base_map.png", directory / "base_map.jpg") if path.is_file()]
        if len(maps) != 1:
            raise ValidationError("stored mission does not contain exactly one base map")
        verification_path = directory / "verification.json"
        if not verification_path.is_file():
            raise ValidationError("stored mission has no verification record")
        return AppliedMission(manifest, directory, maps[0], manifest_path, verification_path)

    @staticmethod
    def _latest_version(directory: Path, pattern: re.Pattern[str]) -> int | None:
        versions = []
        if directory.is_dir():
            for path in directory.iterdir():
                match = pattern.fullmatch(path.name)
                if path.is_file() and match:
                    versions.append(int(match.group(1)))
        return max(versions, default=None)

    def save_semantic_result(self, mission_id: str, mission_version: int, result: Mapping[str, Any]) -> Path:
        directory = self.mission_directory(mission_id, mission_version)
        if not directory.is_dir():
            raise ValidationError("mission version is not stored")
        validated = validate_semantic_result(result, mission_id)
        if validated["base_map_version"] != mission_version:
            raise ValidationError("semantic_result base_map_version does not match mission")
        version = validated["result_version"]
        with self._lock:
            latest = self._latest_version(directory, RESULT_RE)
            if latest is not None and version <= latest:
                raise StaleVersionError(f"semantic result version {version} is not newer than {latest}")
            immutable = directory / f"semantic_result_v{version}.json"
            if immutable.exists():
                raise StaleVersionError("semantic result version already exists")
            atomic_write_json(immutable, validated)
            atomic_write_json(directory / "semantic_result.json", validated)
        return immutable

    def latest_result_version(self, mission_id: str, mission_version: int) -> int | None:
        return self._latest_version(self.mission_directory(mission_id, mission_version), RESULT_RE)

    def load_semantic_result(self, mission_id: str, mission_version: int, result_version: int | None = None) -> dict[str, Any]:
        directory = self.mission_directory(mission_id, mission_version)
        if not directory.is_dir():
            raise ValidationError("mission version is not stored")
        selected = result_version
        if selected is None:
            selected = self.latest_result_version(mission_id, mission_version)
        if isinstance(selected, bool) or not isinstance(selected, int) or selected < 1:
            raise ValidationError("semantic result is not stored")
        value = self._read_json(directory / f"semantic_result_v{selected}.json")
        validated = validate_semantic_result(value, mission_id)
        if validated["base_map_version"] != mission_version:
            raise ValidationError("semantic_result base_map_version does not match mission")
        if validated["result_version"] != selected:
            raise ValidationError("semantic_result filename version does not match content")
        return validated

    def apply_approved_plan(self, mission_id: str, mission_version: int, plan: Mapping[str, Any] | Path) -> Path:
        directory = self.mission_directory(mission_id, mission_version)
        if not directory.is_dir():
            raise ValidationError("mission version is not stored")
        latest_result = self.latest_result_version(mission_id, mission_version)
        if latest_result is None:
            raise ValidationError("no semantic result exists for approved plan")
        value = self._read_json(plan) if isinstance(plan, Path) else plan
        validated = validate_approved_plan(
            value,
            expected_mission_id=mission_id,
            expected_mission_version=mission_version,
            expected_result_version=latest_result,
        )
        plan_version = validated["approved_plan_version"]
        with self._lock:
            latest_plan = self._latest_version(directory, PLAN_RE)
            if latest_plan is not None and plan_version <= latest_plan:
                raise StaleVersionError(f"approved plan version {plan_version} is not newer than {latest_plan}")
            immutable = directory / f"approved_plan_v{plan_version}.json"
            atomic_write_json(immutable, validated)
            atomic_write_json(directory / "approved_plan.json", validated)
        return immutable
