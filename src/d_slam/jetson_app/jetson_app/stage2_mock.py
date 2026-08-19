"""Small deterministic Stage 2 artifacts used before Stage 3 sensors are wired."""
from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, PngImagePlugin

from .domain import Pose2D, SemanticResult
from .mission import MissionManager
from .storage import atomic_write_bytes, atomic_write_json


@dataclass(frozen=True)
class Stage2MockArtifacts:
    mission_id: str
    mission_version: int
    result_version: int
    semantic_result_path: Path
    map_preview_path: Path


class Stage2MockGenerator:
    def __init__(self, manager: MissionManager) -> None:
        self.manager = manager

    def generate(
        self,
        mission_id: str | None = None,
        mission_version: int | None = None,
    ) -> Stage2MockArtifacts:
        if mission_id is None or mission_version is None:
            current = self.manager.current_mission_ref()
            if current is None:
                raise ValueError("no active mission is available for Stage 2 mock analysis")
            mission_id, mission_version = current
        mission = self.manager.load_mission(mission_id, int(mission_version))
        result_version = (
            self.manager.latest_result_version(mission_id, int(mission_version)) or 0
        ) + 1
        start = mission.manifest.robot_start
        result = SemanticResult(
            mission_id=mission_id,
            base_map_version=int(mission_version),
            result_version=result_version,
            coordinate_frame="mission_map",
            robot_pose=Pose2D(start.x, start.y, start.yaw),
            trajectory=(Pose2D(start.x, start.y, start.yaw),),
            victim_candidates=(),
            confirmed_victims=(),
            obstacles=(),
            risks=(),
            routes=(),
            recommendations=(),
            safe_waiting_points=(),
            explored_areas=(),
            unknown_areas=(),
            slam_map_version=1,
            map_alignment={"mode": "stage2_mock", "status": "not_run"},
            source="stage2_mock",
            confidence=0.5,
            analysis_mode="mock",
        )
        semantic_path = self.manager.save_semantic_result(
            mission_id, int(mission_version), result.to_dict()
        )

        with Image.open(mission.base_map_path) as source:
            image = source.convert("RGB")
            width, height = image.size
            info = PngImagePlugin.PngInfo()
            info.add_text("frame_id", "mission_map")
            info.add_text("map_version", "1")
            info.add_text("mission_id", mission_id)
            info.add_text("base_map_version", str(mission_version))
            info.add_text("artifact_version", str(result_version))
            info.add_text("source_grid_size", f"{width}x{height}")
            info.add_text("downsample_block", "1")
            info.add_text(
                "resolution_m_per_cell", str(mission.manifest.meters_per_pixel)
            )
            info.add_text("origin_x_m", "0.0")
            info.add_text("origin_y_m", "0.0")
            signature = hashlib.sha256(image.tobytes()).hexdigest()
            info.add_text("content_signature", signature)
            buffer = io.BytesIO()
            image.save(buffer, format="PNG", pnginfo=info, compress_level=9)
        preview_path = mission.directory / "map_preview.png"
        atomic_write_bytes(preview_path, buffer.getvalue())
        atomic_write_json(
            mission.directory / "map_preview.json",
            {
                "mission_id": mission_id,
                "base_map_version": int(mission_version),
                "map_version": 1,
                "artifact_version": result_version,
                "content_signature": signature,
                "analysis_mode": "mock",
                "coordinate_frame": "mission_map",
                "state": "ready",
            },
        )
        return Stage2MockArtifacts(
            mission_id,
            int(mission_version),
            result_version,
            semantic_path,
            preview_path,
        )


__all__ = ["Stage2MockArtifacts", "Stage2MockGenerator"]
