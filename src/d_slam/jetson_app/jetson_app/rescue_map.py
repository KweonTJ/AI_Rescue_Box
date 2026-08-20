"""Mission-frame Semantic Rescue Map preview rendered on the Host prior canvas."""

from __future__ import annotations

import hashlib
import io
import math
from pathlib import Path
from typing import Any, Mapping

from PIL import Image, ImageDraw, PngImagePlugin

from .alignment import RigidMissionTransform
from .domain import MissionManifest, Point2D
from .map_preview import RenderedMapPreview
from .providers import SlamSnapshot
from .stage4 import ChangeMap, PriorMapReference, Stage4Artifacts, Stage4Config


class SemanticRescueMapRenderer:
    """Overlay aligned live evidence and semantic rescue data on the prior map."""

    def __init__(self, *, max_dimension: int = 768, config: Stage4Config | None = None) -> None:
        if max_dimension <= 0:
            raise ValueError("max_dimension must be positive")
        self.max_dimension = max_dimension
        self.config = config or Stage4Config()

    @staticmethod
    def _transform_from_result(result: Mapping[str, Any]) -> RigidMissionTransform | None:
        alignment = result.get("map_alignment")
        if not isinstance(alignment, Mapping) or alignment.get("status") != "aligned":
            return None
        value = alignment.get("T_mission_map_from_slam_map", alignment.get("transform"))
        if not isinstance(value, Mapping):
            return None
        try:
            return RigidMissionTransform(
                float(value.get("translation_x_m", 0.0)),
                float(value.get("translation_y_m", 0.0)),
                float(value.get("yaw_radians", 0.0)),
                "prior_live_alignment",
                "aligned",
            )
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _point(value: Any) -> Point2D | None:
        if not isinstance(value, Mapping):
            return None
        try:
            return Point2D(float(value["x"]), float(value["y"]))
        except (KeyError, TypeError, ValueError):
            return None

    def _pixel(self, prior: PriorMapReference, point: Point2D) -> tuple[int, int]:
        x, y = prior.mission_to_image(point)
        return int(round(x)), int(round(y))

    def render(
        self,
        *,
        mission: MissionManifest,
        prior_map_path: Path,
        snapshot: SlamSnapshot,
        result: Mapping[str, Any],
        artifacts: Stage4Artifacts | None = None,
        artifact_version: int | None = None,
    ) -> RenderedMapPreview:
        transform = self._transform_from_result(result)
        if transform is None:
            raise ValueError("semantic rescue preview requires an aligned Stage 4 transform")
        prior = (
            artifacts.prior
            if artifacts is not None
            else PriorMapReference.from_image(
                mission,
                prior_map_path,
                dark_threshold=self.config.prior_dark_threshold,
                free_threshold=self.config.prior_free_threshold,
            )
        )
        change: ChangeMap | None = artifacts.change if artifacts is not None else None

        with Image.open(prior_map_path) as source:
            canvas = source.convert("RGBA")
        overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay, "RGBA")
        grid = snapshot.occupancy_grid
        live_half = max(1, int(round(grid.resolution / prior.meters_per_pixel / 2.0)))

        for y in range(grid.height):
            for x in range(grid.width):
                value = grid.value(x, y)
                if value == -1:
                    continue
                mission_point = transform.slam_to_mission_point(grid.cell_to_world((x, y)))
                px, py = self._pixel(prior, mission_point)
                if not (0 <= px < prior.width and 0 <= py < prior.height):
                    continue
                fill = (35, 35, 35, 210) if value >= 65 else (80, 135, 180, 45)
                draw.rectangle(
                    (px - live_half, py - live_half, px + live_half, py + live_half),
                    fill=fill,
                )

        for polygon_value in result.get("unknown_areas", ()):
            polygon = [
                self._pixel(prior, point)
                for point in (self._point(value) for value in polygon_value)
                if point is not None
            ]
            if len(polygon) >= 3:
                draw.polygon(polygon, fill=(110, 80, 180, 30), outline=(110, 80, 180, 110))
        for polygon_value in result.get("explored_areas", ()):
            polygon = [
                self._pixel(prior, point)
                for point in (self._point(value) for value in polygon_value)
                if point is not None
            ]
            if len(polygon) >= 2:
                draw.line(polygon + [polygon[0]], fill=(50, 120, 160, 120), width=1)

        if change is not None:
            for item in change.changed_points:
                point = self._point(item.get("mission_position"))
                if point is None:
                    continue
                px, py = self._pixel(prior, point)
                fill = (220, 45, 45, 230) if item.get("state") == "newly_blocked" else (35, 150, 220, 220)
                radius = max(2, live_half + 1)
                draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=fill)

        for obstacle in result.get("obstacles", ()):
            polygon = [
                self._pixel(prior, point)
                for point in (self._point(value) for value in obstacle)
                if point is not None
            ]
            if len(polygon) >= 2:
                draw.line(polygon + [polygon[0]], fill=(75, 30, 25, 200), width=2)

        for risk in result.get("risk_zones", ()):
            if not isinstance(risk, Mapping):
                continue
            polygon = []
            for value in risk.get("polygon", ()):
                point = self._point(value)
                if point is not None:
                    polygon.append(self._pixel(prior, point))
            if len(polygon) >= 2:
                severity = float(risk.get("severity", 0.0) or 0.0)
                alpha = int(50 + max(0.0, min(1.0, severity)) * 90)
                draw.polygon(polygon, fill=(220, 80, 35, alpha), outline=(180, 55, 25, 210))

        seen_targets: set[str] = set()
        for route in result.get("entry_routes", ()):
            if not isinstance(route, Mapping):
                continue
            points = []
            for value in route.get("points", ()):
                point = self._point(value)
                if point is not None:
                    points.append(self._pixel(prior, point))
            if len(points) >= 2:
                target = str(route.get("target_id") or "")
                is_best = target not in seen_targets
                seen_targets.add(target)
                draw.line(points, fill=(25, 105, 210, 230), width=4 if is_best else 2)

        for victim in result.get("victim_candidates", ()):
            if not isinstance(victim, Mapping):
                continue
            point = self._point(victim.get("map_position"))
            if point is None:
                continue
            px, py = self._pixel(prior, point)
            draw.ellipse((px - 5, py - 5, px + 5, py + 5), fill=(245, 145, 30, 245))

        for victim in result.get("confirmed_victims", ()):
            if not isinstance(victim, Mapping):
                continue
            point = self._point(victim.get("map_position"))
            if point is None:
                continue
            px, py = self._pixel(prior, point)
            draw.ellipse((px - 7, py - 7, px + 7, py + 7), outline=(190, 35, 45, 255), width=3)

        for safe in result.get("safe_waiting_points", ()):
            point = self._point(safe)
            if point is None:
                continue
            px, py = self._pixel(prior, point)
            draw.ellipse(
                (px - 6, py - 6, px + 6, py + 6),
                fill=(30, 175, 95, 225),
                outline=(10, 95, 50, 255),
                width=2,
            )

        composed = Image.alpha_composite(canvas, overlay).convert("RGB")
        source_width, source_height = composed.size
        block = max(1, math.ceil(max(source_width, source_height) / self.max_dimension))
        target_size = (math.ceil(source_width / block), math.ceil(source_height / block))
        if target_size != composed.size:
            composed = composed.resize(target_size, Image.Resampling.LANCZOS)
        geometry = (
            f"mission_map|{source_width}x{source_height}|{prior.meters_per_pixel:.17g}|"
            f"block={block}|aligned={result.get('map_alignment', {}).get('confidence', 0)}"
        ).encode()
        signature = hashlib.sha256(geometry + b"\0" + composed.tobytes()).hexdigest()
        origin = prior.image_to_mission(0.0, float(prior.height - 1))
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("frame_id", "mission_map")
        metadata.add_text("map_version", str(snapshot.map_version))
        metadata.add_text("content_signature", signature)
        metadata.add_text("source_grid_size", f"{source_width}x{source_height}")
        metadata.add_text("downsample_block", str(block))
        metadata.add_text("resolution_m_per_cell", f"{prior.meters_per_pixel:.17g}")
        metadata.add_text("origin_x_m", f"{origin.x:.17g}")
        metadata.add_text("origin_y_m", f"{origin.y:.17g}")
        metadata.add_text("mission_id", mission.mission_id)
        metadata.add_text("base_map_version", str(mission.mission_version))
        metadata.add_text("artifact_version", str(artifact_version or result.get("result_version", 1)))
        output = io.BytesIO()
        composed.save(output, format="PNG", pnginfo=metadata, compress_level=9)
        return RenderedMapPreview(output.getvalue(), signature, composed.width, composed.height)


__all__ = ["SemanticRescueMapRenderer"]
