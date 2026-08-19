from __future__ import annotations

import hashlib
import io
import math
from dataclasses import dataclass

from PIL import Image, PngImagePlugin

from .providers import SlamSnapshot


@dataclass(frozen=True)
class RenderedMapPreview:
    png: bytes
    content_signature: str
    width: int
    height: int


class OccupancyPreviewRenderer:
    FREE_COLOR = (248, 250, 252)
    UNCERTAIN_COLOR = (245, 158, 11)
    UNKNOWN_COLOR = (124, 58, 237)
    OCCUPIED_COLOR = (17, 24, 39)

    def __init__(self, *, occupied_threshold: int = 65, max_dimension: int = 768) -> None:
        if not 0 <= occupied_threshold <= 100 or max_dimension <= 0:
            raise ValueError("invalid preview settings")
        self.occupied_threshold = occupied_threshold
        self.max_dimension = max_dimension

    def render(self, snapshot: SlamSnapshot, *, mission_id: str | None = None, base_map_version: int | None = None, artifact_version: int | None = None) -> RenderedMapPreview:
        grid = snapshot.occupancy_grid
        scale = max(1, math.ceil(max(grid.width, grid.height) / self.max_dimension))
        width = math.ceil(grid.width / scale)
        height = math.ceil(grid.height / scale)
        pixels = []
        for image_y in range(height):
            block_y = height - image_y - 1
            y_start, y_stop = block_y * scale, min(grid.height, (block_y + 1) * scale)
            for image_x in range(width):
                x_start, x_stop = image_x * scale, min(grid.width, (image_x + 1) * scale)
                values = [grid.value(x, y) for y in range(y_start, y_stop) for x in range(x_start, x_stop)]
                if any(value >= self.occupied_threshold for value in values):
                    color = self.OCCUPIED_COLOR
                elif any(value == -1 for value in values):
                    color = self.UNKNOWN_COLOR
                elif any(value > 0 for value in values):
                    color = self.UNCERTAIN_COLOR
                else:
                    color = self.FREE_COLOR
                pixels.append(color)
        image = Image.new("RGB", (width, height))
        image.putdata(pixels)
        geometry = f"{width}x{height}|{grid.width}x{grid.height}|{grid.resolution:.17g}|{grid.origin.x:.17g},{grid.origin.y:.17g}|{grid.frame_id}|threshold={self.occupied_threshold}".encode()
        signature = hashlib.sha256(geometry + b"\0" + image.tobytes()).hexdigest()
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("frame_id", grid.frame_id)
        metadata.add_text("map_version", str(snapshot.map_version))
        metadata.add_text("content_signature", signature)
        if mission_id is not None: metadata.add_text("mission_id", mission_id)
        if base_map_version is not None: metadata.add_text("base_map_version", str(base_map_version))
        if artifact_version is not None: metadata.add_text("artifact_version", str(artifact_version))
        output = io.BytesIO()
        image.save(output, format="PNG", pnginfo=metadata, compress_level=9)
        return RenderedMapPreview(output.getvalue(), signature, width, height)


__all__ = ["OccupancyPreviewRenderer", "RenderedMapPreview"]
