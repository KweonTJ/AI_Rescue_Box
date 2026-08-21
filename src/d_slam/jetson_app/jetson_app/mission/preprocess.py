"""OpenCV preprocessing for Tablet-provided mission floorplans.

The original image is never modified.  This module creates two derived PNGs:
``base_map_display.png`` for the operator UI and ``wall_mask.png`` for later
computer-vision/structure analysis.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FloorplanProcessingResult:
    display_png: bytes
    wall_mask_png: bytes
    metadata: dict[str, Any]


class FloorplanPreprocessor:
    """Create conservative monochrome floorplan derivatives with OpenCV.

    OpenCV is imported lazily so the rest of the Jetson API can still start and
    report a useful error when the machine image has not been provisioned with
    ``cv2`` yet.
    """

    pipeline_version = "opencv_floorplan_v1"

    def __init__(
        self,
        *,
        clahe_clip_limit: float = 2.0,
        morphology_kernel: int = 3,
        minimum_component_area: int = 4,
    ) -> None:
        if clahe_clip_limit <= 0:
            raise ValueError("clahe_clip_limit must be positive")
        if morphology_kernel < 1 or morphology_kernel % 2 == 0:
            raise ValueError("morphology_kernel must be an odd positive integer")
        if minimum_component_area < 1:
            raise ValueError("minimum_component_area must be positive")
        self.clahe_clip_limit = float(clahe_clip_limit)
        self.morphology_kernel = int(morphology_kernel)
        self.minimum_component_area = int(minimum_component_area)

    @staticmethod
    def _png(cv2, image, name: str) -> bytes:
        ok, encoded = cv2.imencode(".png", image)
        if not ok:
            raise RuntimeError(f"OpenCV could not encode {name} PNG")
        return encoded.tobytes()

    def process(self, source: Path) -> FloorplanProcessingResult:
        try:
            import cv2
            import numpy as np
        except ImportError as error:  # pragma: no cover - machine provisioning issue
            raise RuntimeError(
                "OpenCV preprocessing requires the Jetson cv2/numpy modules"
            ) from error

        source = Path(source)
        image = cv2.imread(str(source), cv2.IMREAD_COLOR)
        if image is None or image.size == 0:
            raise ValueError("OpenCV could not decode the base map")

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(
            clipLimit=self.clahe_clip_limit,
            tileGridSize=(8, 8),
        )
        contrast = clahe.apply(gray)
        denoised = cv2.GaussianBlur(contrast, (3, 3), 0)
        threshold_value, binary = cv2.threshold(
            denoised,
            0,
            255,
            cv2.THRESH_BINARY + cv2.THRESH_OTSU,
        )

        # Floorplans normally have a light background.  Normalize scans/photos
        # that arrive inverted so the display result remains visually stable.
        if float(binary.mean()) < 127.5:
            binary = cv2.bitwise_not(binary)

        ink = cv2.bitwise_not(binary)
        kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (self.morphology_kernel, self.morphology_kernel),
        )
        connected = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, kernel, iterations=1)

        component_count, labels, stats, _ = cv2.connectedComponentsWithStats(
            connected,
            connectivity=8,
        )
        cleaned = np.zeros_like(connected)
        kept_components = 0
        removed_components = 0
        for label in range(1, component_count):
            area = int(stats[label, cv2.CC_STAT_AREA])
            if area >= self.minimum_component_area:
                cleaned[labels == label] = 255
                kept_components += 1
            else:
                removed_components += 1

        # Display map: almost-white neutral background with dark gray structure
        # lines.  Semantic overlays remain high-contrast on top of this image.
        display = np.full_like(cleaned, 248)
        display[cleaned > 0] = 52

        height, width = cleaned.shape
        metadata = {
            "pipeline": self.pipeline_version,
            "opencv_version": str(cv2.__version__),
            "width": int(width),
            "height": int(height),
            "grayscale": True,
            "display_background": 248,
            "display_structure": 52,
            "threshold_method": "otsu",
            "otsu_threshold": float(threshold_value),
            "clahe_clip_limit": self.clahe_clip_limit,
            "morphology": {
                "operation": "close",
                "kernel": self.morphology_kernel,
                "iterations": 1,
            },
            "minimum_component_area": self.minimum_component_area,
            "kept_components": kept_components,
            "removed_components": removed_components,
            "wall_mask_semantics": "white=detected_structure, black=background",
            "steps": [
                "grayscale",
                "clahe",
                "gaussian_blur",
                "otsu_threshold",
                "polarity_normalization",
                "morphology_close",
                "small_component_filter",
            ],
        }
        return FloorplanProcessingResult(
            display_png=self._png(cv2, display, "display map"),
            wall_mask_png=self._png(cv2, cleaned, "wall mask"),
            metadata=metadata,
        )
