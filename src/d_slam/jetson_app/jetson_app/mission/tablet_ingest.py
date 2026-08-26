"""Tablet -> Jetson Mission creation boundary.

Tablet sends an image-space mission draft and, for a new/changed floorplan, the
JPEG/PNG bytes.  Jetson owns canonical manifest generation, immutable version
storage and OpenCV-derived map artifacts.
"""
from __future__ import annotations

import hashlib
import json
import math
import shutil
import tempfile
import uuid
from pathlib import Path, PurePath
from typing import Any, Mapping, Sequence

from PIL import Image, UnidentifiedImageError

from ..domain import MissionManifest, ValidationError, utc_now, validate_mission_id
from ..storage import atomic_copy, atomic_write_bytes, atomic_write_json, sha256_file
from .manager import AppliedMission, MissionManager
from .preprocess import FloorplanPreprocessor, FloorplanProcessingResult


_ALLOWED_SUFFIXES = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG"}


def _finite(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValidationError(f"{name} must be numeric") from error
    if not math.isfinite(number):
        raise ValidationError(f"{name} must be finite")
    return number


def _nonnegative_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValidationError(f"{name} must be a non-negative integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as error:
        raise ValidationError(f"{name} must be a non-negative integer") from error
    if number < 0:
        raise ValidationError(f"{name} must be a non-negative integer")
    return number


def _image_point(value: Any, name: str) -> tuple[float, float]:
    if not isinstance(value, Mapping):
        raise ValidationError(f"{name} must contain x and y")
    return _finite(value.get("x"), f"{name}.x"), _finite(value.get("y"), f"{name}.y")


def _safe_filename(value: str) -> tuple[str, str]:
    if not isinstance(value, str) or not value or value != PurePath(value).name:
        raise ValidationError("base map filename must be a single safe file name")
    if "/" in value or "\\" in value or "\x00" in value:
        raise ValidationError("base map filename must be a single safe file name")
    suffix = Path(value).suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise ValidationError("Tablet base map must be JPEG or PNG")
    return value, suffix


def _map_point(
    point: tuple[float, float],
    *,
    origin: tuple[float, float],
    meters_per_pixel: float,
    rotation_radians: float,
) -> tuple[float, float]:
    """Match the historical Host image->mission_map convention exactly."""

    dx = (point[0] - origin[0]) * meters_per_pixel
    dy = -(point[1] - origin[1]) * meters_per_pixel
    cosine = math.cos(rotation_radians)
    sine = math.sin(rotation_radians)
    return cosine * dx - sine * dy, sine * dx + cosine * dy


class TabletMissionIngestor:
    def __init__(
        self,
        manager: MissionManager,
        *,
        preprocessor: FloorplanPreprocessor | None = None,
    ) -> None:
        self.manager = manager
        self.preprocessor = preprocessor or FloorplanPreprocessor()

    def _identity(self, draft: Mapping[str, Any]) -> tuple[str, int, int | None]:
        mission_id_value = draft.get("mission_id")
        if mission_id_value is None or not str(mission_id_value).strip():
            mission_id = f"mission-{uuid.uuid4().hex[:16]}"
        else:
            mission_id = validate_mission_id(str(mission_id_value).strip())

        latest = self.manager.latest_mission_version(mission_id)
        expected = 1 if latest is None else latest + 1
        supplied = draft.get("mission_version")
        if supplied is not None:
            if isinstance(supplied, bool):
                raise ValidationError("mission_version must be a positive integer")
            try:
                supplied_version = int(supplied)
            except (TypeError, ValueError) as error:
                raise ValidationError("mission_version must be a positive integer") from error
            if supplied_version != expected:
                raise ValidationError(
                    f"next mission version for {mission_id} must be v{expected}"
                )
        return mission_id, expected, latest

    def _source_map(
        self,
        temporary: Path,
        *,
        mission_id: str,
        base_map_filename: str | None,
        base_map_bytes: bytes | None,
        reuse_from_version: int | None,
        latest_version: int | None,
    ) -> tuple[Path, str, str, int, int, str, AppliedMission | None]:
        reused: AppliedMission | None = None
        if base_map_bytes is not None:
            if base_map_filename is None:
                raise ValidationError("base map filename is required with image bytes")
            source_name, suffix = _safe_filename(base_map_filename)
            if not 0 < len(base_map_bytes) <= self.manager.max_map_bytes:
                raise ValidationError("Tablet base map size is outside the allowed range")
            source = temporary / f"upload{suffix}"
            atomic_write_bytes(source, base_map_bytes)
        else:
            source_version = reuse_from_version
            if source_version is None:
                source_version = latest_version
            if source_version is None:
                raise ValidationError("a new Mission requires a JPEG or PNG base map")
            if isinstance(source_version, bool) or int(source_version) < 1:
                raise ValidationError("reuse_from_version must be a positive integer")
            reused = self.manager.load_mission(mission_id, int(source_version))
            original_candidates = [
                path
                for path in reused.directory.glob("base_map_original.*")
                if path.suffix.lower() in _ALLOWED_SUFFIXES and path.is_file()
            ]
            existing_source = (
                original_candidates[0] if len(original_candidates) == 1 else reused.base_map_path
            )
            suffix = existing_source.suffix.lower()
            source_name = str(
                reused.manifest.extra.get("source_image_filename")
                or reused.manifest.base_map_filename
            )
            source = temporary / f"reused{suffix}"
            atomic_copy(existing_source, source, self.manager.max_map_bytes)

        try:
            with Image.open(source) as image:
                image.verify()
            with Image.open(source) as image:
                width, height = image.size
                image_format = str(image.format)
        except (OSError, UnidentifiedImageError) as error:
            raise ValidationError("Tablet base map is not a valid JPEG or PNG image") from error
        expected_format = _ALLOWED_SUFFIXES.get(source.suffix.lower())
        if image_format not in {"JPEG", "PNG"} or image_format != expected_format:
            raise ValidationError("Tablet base map content does not match its extension")
        digest = sha256_file(source)
        stored_filename = "base_map.jpg" if image_format == "JPEG" else "base_map.png"
        return source, source_name, stored_filename, int(width), int(height), digest, reused

    def _manifest(
        self,
        draft: Mapping[str, Any],
        *,
        mission_id: str,
        mission_version: int,
        source_image_filename: str,
        stored_map_filename: str,
        base_map_sha256: str,
        width: int,
        height: int,
        reused_from_version: int | None,
    ) -> MissionManifest:
        mission_name = str(draft.get("mission_name", "")).strip()
        if not mission_name:
            raise ValidationError("mission_name is required")

        meters_per_pixel = _finite(draft.get("meters_per_pixel"), "meters_per_pixel")
        if meters_per_pixel <= 0:
            raise ValidationError("meters_per_pixel must be positive")

        robot_image = _image_point(draft.get("robot_start_image"), "robot_start_image")
        image_yaw = _finite(draft.get("initial_yaw"), "initial_yaw")
        entrance_values = draft.get("entrances", ())
        if not isinstance(entrance_values, Sequence) or isinstance(
            entrance_values, (str, bytes)
        ):
            raise ValidationError("entrances must be an array")
        entrance_images = tuple(
            _image_point(value, f"entrances[{index}]")
            for index, value in enumerate(entrance_values)
        )
        if not entrance_images:
            raise ValidationError("at least one entrance is required")

        teams = _nonnegative_int(draft.get("available_teams", 0), "available_teams")
        rescuers = _nonnegative_int(
            draft.get("available_rescuers", 0), "available_rescuers"
        )

        entrances: list[dict[str, Any]] = []
        for index, image_point in enumerate(entrance_images, start=1):
            map_x, map_y = _map_point(
                image_point,
                origin=robot_image,
                meters_per_pixel=meters_per_pixel,
                rotation_radians=image_yaw,
            )
            entrances.append(
                {
                    "id": f"entrance-{index}",
                    "x": map_x,
                    "y": map_y,
                    "map_x": map_x,
                    "map_y": map_y,
                    "image_x": image_point[0],
                    "image_y": image_point[1],
                }
            )

        transform = {
            "image_origin": {"x": robot_image[0], "y": robot_image[1]},
            "meters_per_pixel": meters_per_pixel,
            "rotation_radians": image_yaw,
            "invert_y": True,
            "frame_id": "mission_map",
            "image_y_axis": "down",
            "map_y_axis": "up",
            "robot_start_image": {"x": robot_image[0], "y": robot_image[1]},
            "initial_image_yaw": image_yaw,
            "initial_map_yaw": 0.0,
            "alignment_convention": "image_arrow_aligned_to_map_positive_x",
        }
        value: dict[str, Any] = {
            "schema_version": "1.0",
            "mission_id": mission_id,
            "mission_version": mission_version,
            "artifact_version": mission_version,
            "mission_name": mission_name,
            "created_at": utc_now(),
            "base_map": {
                "filename": stored_map_filename,
                "sha256": base_map_sha256,
                "width": width,
                "height": height,
            },
            "base_map_filename": stored_map_filename,
            "base_map_sha256": base_map_sha256,
            "base_map_width": width,
            "base_map_height": height,
            "meters_per_pixel": meters_per_pixel,
            "robot_start": {
                "x": 0.0,
                "y": 0.0,
                "map_x": 0.0,
                "map_y": 0.0,
                "yaw": 0.0,
                "image_x": robot_image[0],
                "image_y": robot_image[1],
            },
            "initial_yaw": 0.0,
            "entrances": entrances,
            "available_teams": teams,
            "available_rescuers": rescuers,
            "coordinate_frame": "mission_map",
            "coordinate_transform": transform,
            "units": "meters",
            "source": "tablet",
            "confidence": 1.0,
            "notes": str(draft.get("notes", "")),
            "source_image_filename": source_image_filename,
            "tablet_ingest": True,
        }
        if reused_from_version is not None:
            value["reused_base_map_from_version"] = int(reused_from_version)
        return MissionManifest.from_dict(value)

    @staticmethod
    def _reused_processing(
        source_mission: AppliedMission,
    ) -> FloorplanProcessingResult | None:
        display = source_mission.directory / "base_map_display.png"
        mask = source_mission.directory / "wall_mask.png"
        metadata_path = source_mission.directory / "processing.json"
        if not (display.is_file() and mask.is_file() and metadata_path.is_file()):
            return None
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(metadata, dict):
            return None
        return FloorplanProcessingResult(
            display_png=display.read_bytes(),
            wall_mask_png=mask.read_bytes(),
            metadata=dict(metadata),
        )

    def store(
        self,
        draft: Mapping[str, Any],
        *,
        base_map_filename: str | None = None,
        base_map_bytes: bytes | None = None,
        reuse_from_version: int | None = None,
    ) -> AppliedMission:
        if not isinstance(draft, Mapping):
            raise ValidationError("Tablet Mission manifest draft must be a JSON object")
        mission_id, mission_version, latest = self._identity(draft)

        with tempfile.TemporaryDirectory(prefix="ai-rescue-tablet-mission-") as directory:
            temporary = Path(directory)
            (
                source,
                source_image_filename,
                stored_map_filename,
                width,
                height,
                digest,
                reused,
            ) = self._source_map(
                temporary,
                mission_id=mission_id,
                base_map_filename=base_map_filename,
                base_map_bytes=base_map_bytes,
                reuse_from_version=reuse_from_version,
                latest_version=latest,
            )
            actual_reuse_version = (
                reused.manifest.mission_version if reused is not None else None
            )
            manifest = self._manifest(
                draft,
                mission_id=mission_id,
                mission_version=mission_version,
                source_image_filename=source_image_filename,
                stored_map_filename=stored_map_filename,
                base_map_sha256=digest,
                width=width,
                height=height,
                reused_from_version=actual_reuse_version,
            )
            manifest_path = temporary / "mission_manifest.json"
            atomic_write_json(manifest_path, manifest.to_dict())

            processed = self._reused_processing(reused) if reused is not None else None
            if processed is None:
                processed = self.preprocessor.process(source)
            processing = dict(processed.metadata)
            processing.update(
                {
                    "mission_id": mission_id,
                    "mission_version": mission_version,
                    "source_base_map_sha256": digest,
                    "source_image_filename": source_image_filename,
                    "display_sha256": hashlib.sha256(processed.display_png).hexdigest(),
                    "wall_mask_sha256": hashlib.sha256(processed.wall_mask_png).hexdigest(),
                    "reused_from_version": actual_reuse_version,
                    "processed_at": utc_now(),
                }
            )

            applied = self.manager.apply_mission(manifest_path, source)
            try:
                original_extension = applied.base_map_path.suffix.lower()
                atomic_copy(
                    applied.base_map_path,
                    applied.directory / f"base_map_original{original_extension}",
                    self.manager.max_map_bytes,
                )
                atomic_write_bytes(
                    applied.directory / "base_map_display.png",
                    processed.display_png,
                )
                atomic_write_bytes(
                    applied.directory / "wall_mask.png",
                    processed.wall_mask_png,
                )
                atomic_write_json(applied.directory / "processing.json", processing)
                verification = json.loads(
                    applied.verification_path.read_text(encoding="utf-8")
                )
                verification.update(
                    {
                        "source": "tablet",
                        "processing_status": "ready",
                        "display_map_sha256": processing["display_sha256"],
                        "wall_mask_sha256": processing["wall_mask_sha256"],
                    }
                )
                atomic_write_json(applied.verification_path, verification)
            except Exception:
                # This version cannot be advertised STORED unless all derived
                # artifacts promised by the Tablet contract were committed.
                shutil.rmtree(applied.directory, ignore_errors=True)
                raise

        return self.manager.load_mission(mission_id, mission_version)
