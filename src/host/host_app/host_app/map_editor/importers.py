"""Extensible map importers; only validated JPEG/PNG rasters are supported now."""

from __future__ import annotations

import hashlib
import os
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from ..errors import MapImportError, ValidationError


SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png"}
FORMAT_SUFFIXES = {
    "JPEG": {".jpg", ".jpeg"},
    "MPO": {".jpg", ".jpeg"},
    "PNG": {".png"},
}
JPEG_FORMATS = {"JPEG", "MPO"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class NormalizationOptions:
    max_dimension: int = 2048
    jpeg_quality: int = 82
    png_compress_level: int = 6
    max_input_bytes: int = 50 * 1024 * 1024
    max_pixels: int = 40_000_000

    def __post_init__(self) -> None:
        if self.max_dimension < 1:
            raise ValidationError("max_dimension must be positive")
        if not 1 <= self.jpeg_quality <= 95:
            raise ValidationError("jpeg_quality must be between 1 and 95")
        if not 0 <= self.png_compress_level <= 9:
            raise ValidationError("png_compress_level must be between 0 and 9")
        if self.max_input_bytes < 1 or self.max_pixels < 1:
            raise ValidationError("image limits must be positive")


@dataclass(frozen=True)
class ImportedMap:
    original_path: Path
    transmission_path: Path
    image_format: str
    original_width: int
    original_height: int
    width: int
    height: int
    file_size: int
    sha256: str

    @property
    def resolution_text(self) -> str:
        return f"{self.width} x {self.height}"


class MapImporter(ABC):
    @abstractmethod
    def import_map(
        self,
        source: Path,
        destination_dir: Path,
        options: NormalizationOptions | None = None,
    ) -> ImportedMap:
        """Validate ``source`` and create an atomic transmission copy."""


class RasterMapImporter(MapImporter):
    unsupported_message = "현재는 JPEG와 PNG만 지원합니다."

    def _open_validated(
        self, source: Path, options: NormalizationOptions
    ) -> tuple[Image.Image, str, tuple[int, int]]:
        source = Path(source).expanduser()
        if source.suffix.lower() not in SUPPORTED_SUFFIXES:
            raise MapImportError(self.unsupported_message)
        if not source.is_file():
            raise MapImportError(f"구조도 파일을 찾을 수 없습니다: {source}")
        size = source.stat().st_size
        if size <= 0 or size > options.max_input_bytes:
            raise MapImportError(
                f"구조도 크기는 1~{options.max_input_bytes} 바이트여야 합니다."
            )
        try:
            with Image.open(source) as probe:
                detected_format = probe.format
                width, height = probe.size
                probe.verify()
            if detected_format not in FORMAT_SUFFIXES:
                raise MapImportError(self.unsupported_message)
            if source.suffix.lower() not in FORMAT_SUFFIXES[detected_format]:
                raise MapImportError("파일 확장자와 실제 이미지 형식이 일치하지 않습니다.")
            if width < 1 or height < 1 or width * height > options.max_pixels:
                raise MapImportError("구조도 해상도가 허용 범위를 벗어났습니다.")
            image = Image.open(source)
            image.load()
        except MapImportError:
            raise
        except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as error:
            raise MapImportError("선택한 파일은 올바른 JPEG 또는 PNG 이미지가 아닙니다.") from error
        normalized_format = "JPEG" if detected_format in JPEG_FORMATS else detected_format
        return image, normalized_format, (width, height)

    def import_map(
        self,
        source: Path,
        destination_dir: Path,
        options: NormalizationOptions | None = None,
    ) -> ImportedMap:
        options = options or NormalizationOptions()
        source = Path(source).expanduser()
        destination_dir = Path(destination_dir).expanduser()
        image, image_format, original_size = self._open_validated(source, options)
        try:
            normalized = ImageOps.exif_transpose(image)
            normalized.thumbnail(
                (options.max_dimension, options.max_dimension), Image.Resampling.LANCZOS
            )
            if image_format == "JPEG":
                if normalized.mode not in {"RGB", "L"}:
                    background = Image.new("RGB", normalized.size, "white")
                    if "A" in normalized.getbands():
                        background.paste(normalized, mask=normalized.getchannel("A"))
                    else:
                        background.paste(normalized.convert("RGB"))
                    normalized = background
                suffix = ".jpg" if source.suffix.lower() == ".jpg" else ".jpeg"
                save_options = {
                    "format": "JPEG",
                    "quality": options.jpeg_quality,
                    "optimize": True,
                }
            else:
                suffix = ".png"
                save_options = {
                    "format": "PNG",
                    "compress_level": options.png_compress_level,
                    "optimize": True,
                }
            destination_dir.mkdir(parents=True, exist_ok=True)
            destination = destination_dir / f"base_map{suffix}"
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".base_map-", suffix=f"{suffix}.part", dir=destination_dir
            )
            os.close(descriptor)
            temporary = Path(temporary_name)
            try:
                normalized.save(temporary, **save_options)
                # Windows may reject fsync() on a read-only descriptor. Re-open
                # the completed temporary image with write capability before
                # forcing it to disk, while keeping the atomic replace flow.
                with temporary.open("rb+") as completed:
                    completed.flush()
                    os.fsync(completed.fileno())
                os.replace(temporary, destination)
            except Exception:
                temporary.unlink(missing_ok=True)
                raise
        except MapImportError:
            raise
        except (OSError, ValueError) as error:
            raise MapImportError(f"전송용 구조도를 만들 수 없습니다: {error}") from error
        finally:
            image.close()
        width, height = normalized.size
        return ImportedMap(
            original_path=source.resolve(),
            transmission_path=destination.resolve(),
            image_format=image_format,
            original_width=original_size[0],
            original_height=original_size[1],
            width=width,
            height=height,
            file_size=destination.stat().st_size,
            sha256=sha256_file(destination),
        )
