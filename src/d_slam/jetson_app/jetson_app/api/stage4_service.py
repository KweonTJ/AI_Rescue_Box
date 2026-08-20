"""Stage 4 extension of the existing Jetson local API service.

Only analysis/preview persistence changes here. Transport, review, mission
selection and Stage 2 SubmitRescueUpdate paths remain owned by the existing
service and src/uwb.
"""

from __future__ import annotations

from typing import Any, Mapping

from ..rescue_map import SemanticRescueMapRenderer
from ..stage4 import PriorMapReference, Stage4Artifacts, Stage4Config
from ..storage import atomic_write_bytes, atomic_write_json
from .service import ApiUnavailableError, JetsonApiService


class Stage4JetsonApiService(JetsonApiService):
    def __init__(
        self,
        *args: Any,
        stage4_config: Stage4Config | None = None,
        rescue_preview_renderer: SemanticRescueMapRenderer | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.stage4_config = stage4_config or Stage4Config()
        self.rescue_preview_renderer = rescue_preview_renderer or SemanticRescueMapRenderer(
            config=self.stage4_config
        )

    def health(self):
        value = dict(super().health())
        value["analysis_stage"] = "stage4"
        return value

    def status(self):
        value = dict(super().status())
        value["analysis_stage"] = "stage4"
        return value

    @staticmethod
    def _is_aligned(result: Mapping[str, Any] | None) -> bool:
        if not isinstance(result, Mapping):
            return False
        alignment = result.get("map_alignment")
        return bool(
            isinstance(alignment, Mapping)
            and alignment.get("status") == "aligned"
            and alignment.get("automatic_map_alignment") is True
        )

    def _stored_result_if_any(self, mission) -> Mapping[str, Any] | None:
        latest = self.manager.latest_result_version(
            mission.manifest.mission_id, mission.manifest.mission_version
        )
        if latest is None:
            return None
        return self.manager.load_semantic_result(
            mission.manifest.mission_id, mission.manifest.mission_version, latest
        )

    def _write_stage4_artifacts(self, mission, artifacts: Stage4Artifacts) -> None:
        atomic_write_json(mission.directory / "alignment.json", artifacts.alignment.metadata())
        atomic_write_json(mission.directory / "change_map.json", artifacts.change.metadata())
        atomic_write_json(
            mission.directory / "traversability.json", artifacts.traversability.metadata()
        )
        atomic_write_json(mission.directory / "stage4_analysis.json", artifacts.metadata())

    def _write_preview(
        self,
        mission,
        *,
        artifact_version: int,
        result: Mapping[str, Any] | None = None,
        artifacts: Stage4Artifacts | None = None,
    ) -> dict[str, Any]:
        if self.pipeline is None:
            raise ApiUnavailableError("analysis pipeline is not configured")
        if result is None:
            result = self._stored_result_if_any(mission)
        if not self._is_aligned(result):
            metadata = dict(
                super()._write_preview(mission, artifact_version=artifact_version)
            )
            metadata["coordinate_frame"] = metadata.get("frame_id", "slam_map")
            metadata["preview_kind"] = "raw_live_fallback"
            atomic_write_json(mission.directory / "map_preview.json", metadata)
            return metadata
        try:
            snapshot = self.pipeline.slam.snapshot()
        except Exception as error:
            raise ApiUnavailableError(str(error)) from error
        assert result is not None
        rendered = self.rescue_preview_renderer.render(
            mission=mission.manifest,
            prior_map_path=mission.base_map_path,
            snapshot=snapshot,
            result=result,
            artifacts=artifacts,
            artifact_version=artifact_version,
        )
        atomic_write_bytes(mission.directory / "map_preview.png", rendered.png)
        prior = (
            artifacts.prior
            if artifacts is not None
            else PriorMapReference.from_image(
                mission.manifest,
                mission.base_map_path,
                dark_threshold=self.stage4_config.prior_dark_threshold,
                free_threshold=self.stage4_config.prior_free_threshold,
            )
        )
        origin = prior.image_to_mission(0.0, float(prior.height - 1))
        grid = snapshot.occupancy_grid
        metadata = {
            "mission_id": mission.manifest.mission_id,
            "base_map_version": mission.manifest.mission_version,
            "map_version": snapshot.map_version,
            "artifact_version": artifact_version,
            "frame_id": "mission_map",
            "coordinate_frame": "mission_map",
            "analysis_mode": self.mode,
            "resolution_m_per_cell": prior.meters_per_pixel,
            "origin": origin.to_dict(),
            "coordinate_transform": dict(mission.manifest.coordinate_transform),
            "source_grid": {"width": prior.width, "height": prior.height},
            "preview": {"width": rendered.width, "height": rendered.height},
            "content_signature": rendered.content_signature,
            "map_alignment": result.get("map_alignment"),
            "raw_live_map": {
                "frame_id": grid.frame_id,
                "resolution_m_per_cell": grid.resolution,
                "origin": grid.origin.to_dict(),
                "width": grid.width,
                "height": grid.height,
            },
            "layers": [
                "prior_map",
                "aligned_live_map",
                "change_map",
                "victims",
                "risk_zones",
                "candidate_routes",
                "safe_zones",
            ],
            "download_url": "/api/v1/preview/current.png",
            "state": "ready",
        }
        atomic_write_json(mission.directory / "map_preview.json", metadata)
        return metadata

    def analyze(self):
        if self.pipeline is None:
            raise ApiUnavailableError("analysis pipeline is not configured")
        mission = self._mission()
        self._require_analysis_ready()
        version = (
            self.manager.latest_result_version(
                mission.manifest.mission_id, mission.manifest.mission_version
            )
            or 0
        ) + 1
        try:
            report = self.pipeline.run(
                mission=mission.manifest,
                candidates=self._candidates(),
                result_version=version,
                priorities={},
                prior_map_path=mission.base_map_path,
            )
        except Exception as error:
            if self.mode == "real" and "unavailable" in str(error).lower():
                raise ApiUnavailableError(str(error)) from error
            raise
        result = report.result.to_dict()
        self.manager.save_semantic_result(
            mission.manifest.mission_id,
            mission.manifest.mission_version,
            result,
        )
        if report.stage4_artifacts is not None:
            self._write_stage4_artifacts(mission, report.stage4_artifacts)
        preview = self._write_preview(
            mission,
            artifact_version=version,
            result=result,
            artifacts=report.stage4_artifacts,
        )
        self.events.publish(
            "analysis.completed",
            {
                "mission_id": mission.manifest.mission_id,
                "result_version": version,
                "analysis_mode": result["analysis_mode"],
                "analysis_stage": "stage4",
                "alignment_status": result.get("map_alignment", {}).get("status"),
            },
        )
        return {
            "result": result,
            "analysis_mode": result["analysis_mode"],
            "unreachable_candidate_ids": list(report.unreachable_candidate_ids),
            "map_preview": preview,
        }


__all__ = ["Stage4JetsonApiService"]
