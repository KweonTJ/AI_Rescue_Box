"""Mission/version directories that never overwrite applied artifacts."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Mapping

from PIL import Image, UnidentifiedImageError

from ..errors import StaleVersionError, ValidationError
from ..map_editor.importers import JPEG_FORMATS, sha256_file
from ..mission.models import MissionManifest, SemanticResult, positive_int, validate_mission_id
from ..mission.review import ApprovedPlan
from .atomic import atomic_copy, atomic_write_json


class MissionStore:
    def __init__(
        self, data_root: Path, *, max_original_map_bytes: int = 50 * 1024 * 1024
    ):
        if max_original_map_bytes < 1:
            raise ValidationError("max_original_map_bytes must be positive")
        self.root = Path(data_root).expanduser() / "missions"
        self.max_original_map_bytes = max_original_map_bytes
        self.root.mkdir(parents=True, exist_ok=True)

    def mission_dir(self, mission_id: str, mission_version: int) -> Path:
        mission_id = validate_mission_id(mission_id)
        version = positive_int(mission_version, "mission_version")
        return self.root / mission_id / f"v{version}"

    def list_versions(self, mission_id: str) -> tuple[int, ...]:
        mission_root = self.root / validate_mission_id(mission_id)
        if not mission_root.exists():
            return ()
        versions = []
        for path in mission_root.iterdir():
            if path.is_dir() and path.name.startswith("v") and path.name[1:].isdigit():
                versions.append(int(path.name[1:]))
        return tuple(sorted(versions))

    def next_mission_version(self, mission_id: str) -> int:
        versions = self.list_versions(mission_id)
        return versions[-1] + 1 if versions else 1

    def _original_map_info(self, source: Path) -> tuple[str, str, int, int, int]:
        source = Path(source).expanduser()
        if source.is_symlink() or not source.is_file():
            raise ValidationError("original map must be a regular non-symlink file")
        file_size = source.stat().st_size
        if not 0 < file_size <= self.max_original_map_bytes:
            raise ValidationError("original map size is outside the allowed range")
        suffix = source.suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png"}:
            raise ValidationError("original map must be JPEG or PNG")
        try:
            with Image.open(source) as image:
                image_format = image.format
                width, height = image.size
                image.verify()
        except (OSError, UnidentifiedImageError) as error:
            raise ValidationError("original map is not a valid JPEG or PNG") from error
        valid_content = (
            image_format == "PNG"
            if suffix == ".png"
            else image_format in JPEG_FORMATS
        )
        if not valid_content:
            raise ValidationError("original map content and extension do not match")
        return suffix, sha256_file(source), file_size, width, height

    def save_mission(
        self,
        manifest: MissionManifest,
        base_map_path: Path,
        original_map_path: Path | None = None,
    ) -> Path:
        base_map_path = Path(base_map_path).expanduser()
        if not base_map_path.is_file():
            raise ValidationError("base map file does not exist")
        if sha256_file(base_map_path) != manifest.base_map.sha256:
            raise ValidationError("base map SHA-256 does not match manifest")
        original_info = (
            self._original_map_info(original_map_path)
            if original_map_path is not None
            else None
        )
        target = self.mission_dir(manifest.mission_id, manifest.mission_version)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            manifest_path = target / "mission_manifest.json"
            stored_map = target / manifest.base_map.filename
            identical = (
                manifest_path.is_file()
                and stored_map.is_file()
                and self.load_json(manifest_path) == manifest.to_dict()
                and sha256_file(stored_map) == manifest.base_map.sha256
            )
            if identical and original_info is not None:
                original_path = target / f"original_map{original_info[0]}"
                identical = (
                    original_path.is_file()
                    and sha256_file(original_path) == original_info[1]
                )
            if identical:
                return target
            raise StaleVersionError(
                "mission version already exists with different content"
            )
        temporary = Path(
            tempfile.mkdtemp(prefix=f".v{manifest.mission_version}-", dir=target.parent)
        )
        try:
            atomic_copy(base_map_path, temporary / manifest.base_map.filename)
            atomic_write_json(temporary / "mission_manifest.json", manifest.to_dict())
            if original_info is not None:
                suffix, digest, size, width, height = original_info
                original_filename = f"original_map{suffix}"
                atomic_copy(original_map_path, temporary / original_filename)
                atomic_write_json(
                    temporary / "original_map_metadata.json",
                    {
                        "stored_filename": original_filename,
                        "source_filename": Path(original_map_path).name,
                        "sha256": digest,
                        "file_size": size,
                        "width": width,
                        "height": height,
                        "preserved_without_normalization": True,
                    },
                )
            if target.exists():
                raise StaleVersionError(
                    "mission version already exists and will not be overwritten"
                )
            os.replace(temporary, target)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return target

    def load_manifest(self, mission_id: str, mission_version: int) -> MissionManifest:
        path = self.mission_dir(mission_id, mission_version) / "mission_manifest.json"
        try:
            with path.open("r", encoding="utf-8") as source:
                value = json.load(source)
        except (OSError, json.JSONDecodeError) as error:
            raise ValidationError(f"cannot load mission manifest: {error}") from error
        manifest = MissionManifest.from_dict(value)
        if manifest.mission_id != mission_id or manifest.mission_version != mission_version:
            raise ValidationError("stored manifest path and identity do not match")
        return manifest

    def _versioned_artifact_path(
        self,
        mission_id: str,
        mission_version: int,
        folder: str,
        prefix: str,
        artifact_version: int,
    ) -> Path:
        version = positive_int(artifact_version, "artifact_version")
        return (
            self.mission_dir(mission_id, mission_version)
            / folder
            / f"{prefix}_v{version}.json"
        )

    def save_semantic_result(
        self, result: SemanticResult, mission_version: int
    ) -> Path:
        mission_dir = self.mission_dir(result.mission_id, mission_version)
        if not mission_dir.is_dir():
            raise ValidationError("mission version must be stored before its result")
        if int(result.to_dict()["base_map_version"]) != mission_version:
            raise ValidationError(
                "semantic_result base_map_version does not match stored mission version"
            )
        path = self._versioned_artifact_path(
            result.mission_id,
            mission_version,
            "results",
            "semantic_result",
            result.result_version,
        )
        try:
            return atomic_write_json(path, result.to_dict())
        except FileExistsError as error:
            raise StaleVersionError("semantic result version already exists") from error

    def save_approved_plan(
        self, plan: ApprovedPlan, mission_version: int
    ) -> Path:
        if plan.mission_version != positive_int(mission_version, "mission_version"):
            raise ValidationError(
                "approved plan mission_version does not match its storage destination"
            )
        mission_dir = self.mission_dir(plan.mission_id, mission_version)
        if not mission_dir.is_dir():
            raise ValidationError("mission version must be stored before its approved plan")
        path = self._versioned_artifact_path(
            plan.mission_id,
            mission_version,
            "plans",
            "approved_plan",
            plan.approved_plan_version,
        )
        try:
            return atomic_write_json(path, plan.to_dict())
        except FileExistsError as error:
            if self.load_json(path) == plan.to_dict():
                return path
            raise StaleVersionError(
                "approved plan version already exists with different content"
            ) from error

    def save_map_preview(
        self,
        mission_id: str,
        mission_version: int,
        preview_version: int,
        source: Path,
        expected_sha256: str,
    ) -> Path:
        mission_dir = self.mission_dir(mission_id, mission_version)
        if not mission_dir.is_dir():
            raise ValidationError("mission version must exist before its map preview")
        source = Path(source)
        if not source.is_file() or source.suffix.lower() != ".png":
            raise ValidationError("map preview must be an existing PNG")
        if sha256_file(source) != expected_sha256:
            raise ValidationError("map preview SHA-256 mismatch")
        version = positive_int(preview_version, "preview_version")
        destination = mission_dir / "previews" / f"map_preview_v{version}.png"
        try:
            return atomic_copy(source, destination)
        except FileExistsError as error:
            if destination.is_file() and sha256_file(destination) == expected_sha256:
                return destination
            raise StaleVersionError(
                "map preview version already exists with different content"
            ) from error

    @staticmethod
    def load_json(path: Path) -> dict[str, Any]:
        try:
            with Path(path).open("r", encoding="utf-8") as source:
                value = json.load(source)
        except (OSError, json.JSONDecodeError) as error:
            raise ValidationError(f"cannot load JSON artifact: {error}") from error
        if not isinstance(value, Mapping):
            raise ValidationError("JSON artifact must be an object")
        return dict(value)
