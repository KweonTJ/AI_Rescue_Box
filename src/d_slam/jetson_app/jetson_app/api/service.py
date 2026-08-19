from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from PIL import Image

from ..analysis import AnalysisPipeline
from ..domain import PersonCandidate, ValidationError
from ..map_preview import OccupancyPreviewRenderer
from ..mission import MissionManager
from ..providers.base import ProviderMode
from ..providers.mock import deterministic_mock_candidates
from ..storage import atomic_write_bytes, atomic_write_json
from .events import EventHub
from .ports import ArtifactTransportPort


class ApiNotFoundError(LookupError):
    pass


class ApiConflictError(RuntimeError):
    pass


class ApiUnavailableError(RuntimeError):
    pass


class JetsonApiService:
    def __init__(
        self,
        manager: MissionManager,
        *,
        pipeline: AnalysisPipeline | None = None,
        preview_renderer: OccupancyPreviewRenderer | None = None,
        candidate_source: Callable[[], Sequence[PersonCandidate]] | None = None,
        transport: ArtifactTransportPort | None = None,
        mode: str | None = None,
        events: EventHub | None = None,
        provider_status_source: Callable[[], Mapping[str, Mapping[str, Any]]] | None = None,
        analysis_readiness: Callable[[], None] | None = None,
        mission_reset: Callable[[], None] | None = None,
        map_alignment_source: Callable[[Any], Mapping[str, Any] | None] | None = None,
    ) -> None:
        self.manager = manager
        self.pipeline = pipeline
        self.preview_renderer = preview_renderer or OccupancyPreviewRenderer()
        self.candidate_source = candidate_source
        self.transport = transport
        self._mode = mode
        self.events = events or EventHub()
        self.provider_status_source = provider_status_source
        self.analysis_readiness = analysis_readiness
        self.mission_reset = mission_reset
        self.map_alignment_source = map_alignment_source
        self._selected = None
        self._lock = threading.RLock()
        try:
            self._runtime_mission_ref = manager.current_mission_ref()
        except (ValidationError, OSError):
            self._runtime_mission_ref = None

    async def execute(self, function, *args, **kwargs):
        return await asyncio.to_thread(function, *args, **kwargs)

    @property
    def mode(self):
        if self._mode in {"real", "mock"}:
            return self._mode
        if self.pipeline is not None:
            provider_mode = self.pipeline.slam.status().mode
            if getattr(provider_mode, "value", provider_mode) == ProviderMode.MOCK.value:
                return "mock"
        return "real"

    def _selected_ref(self):
        selected = self.manager.current_mission_ref()
        with self._lock:
            self._selected = selected
        return selected

    def _component_status(self) -> dict[str, Mapping[str, Any]]:
        if self.provider_status_source is None:
            return {}
        try:
            return dict(self.provider_status_source())
        except Exception as error:
            return {
                "stage3_runtime": {
                    "name": "Stage 3 runtime",
                    "mode": "unavailable",
                    "connected": False,
                    "message": str(error),
                    "code": "RUNTIME_UNAVAILABLE",
                }
            }

    def health(self):
        components = self._component_status()
        relevant = [
            value
            for key, value in components.items()
            if key != "analysis_mode"
        ]
        ready = self.pipeline is not None and (
            self.mode == "mock" or (relevant and all(bool(item.get("connected")) for item in relevant))
        )
        return {
            "status": "ok",
            "stage": "stage01",
            "analysis_stage": "stage3",
            "mode": self.mode,
            "analysis_ready": bool(ready),
            "transport_wired": self.transport is not None,
        }

    def status(self):
        slam = {
            "name": "SLAM",
            "mode": "unavailable",
            "connected": False,
            "message": "analysis pipeline is not configured",
        }
        if self.pipeline is not None:
            state = self.pipeline.slam.status()
            slam = {
                "name": state.name,
                "mode": getattr(state.mode, "value", state.mode),
                "connected": state.connected,
                "message": state.message,
            }
        uwb = (
            dict(self.transport.status())
            if self.transport is not None
            else {
                "name": "UWB transport",
                "mode": "not_wired",
                "connected": False,
                "message": "communication is owned by src/uwb",
            }
        )
        providers = {"slam": slam, "uwb": uwb}
        providers.update(self._component_status())
        return {
            "stage": "stage01",
            "analysis_stage": "stage3",
            "mode": self.mode,
            "current_mission": self._selected_ref(),
            "providers": providers,
            "runtime": {
                "analysis_ready": self.health()["analysis_ready"],
                "transport_wired": self.transport is not None,
                "mock_fallback_allowed": False if self.mode == "real" else True,
            },
        }

    def list_missions(self):
        selected = self._selected_ref()
        return [
            {
                "mission_id": mission_id,
                "mission_version": version,
                "active": selected == (mission_id, version),
            }
            for mission_id, version in self.manager.list_missions()
        ]

    def mission_detail(self, mission_id, mission_version):
        try:
            applied = self.manager.load_mission(mission_id, mission_version)
        except (ValidationError, OSError) as error:
            raise ApiNotFoundError(str(error)) from error
        return {
            "mission_id": mission_id,
            "mission_version": mission_version,
            "manifest": applied.manifest.to_dict(),
            "base_map": {
                "filename": applied.base_map_path.name,
                "download_url": f"/api/v1/missions/{mission_id}/{mission_version}/base-map.png",
            },
        }

    def _reset_for_mission(self, selected: tuple[str, int]) -> None:
        if self._runtime_mission_ref == selected:
            return
        if self.mission_reset is not None:
            self.mission_reset()
        self._runtime_mission_ref = selected

    def select_mission(self, mission_id, mission_version):
        result = self.mission_detail(mission_id, mission_version)
        selected = self.manager.set_current_mission(mission_id, mission_version)
        self._reset_for_mission(selected)
        with self._lock:
            self._selected = selected
        self.events.publish(
            "mission.selected",
            {"mission_id": mission_id, "mission_version": mission_version},
        )
        return result

    def current_mission(self):
        selected = self._selected_ref()
        if selected is None:
            raise ApiNotFoundError("no mission is selected")
        return self.mission_detail(*selected)

    def _mission(self):
        selected = self._selected_ref()
        if selected is None:
            raise ApiConflictError("select a mission first")
        self._reset_for_mission(selected)
        return self.manager.load_mission(*selected)

    def base_map_png(self, mission_id, mission_version):
        import io

        applied = self.manager.load_mission(mission_id, mission_version)
        output = io.BytesIO()
        with Image.open(applied.base_map_path) as image:
            image.convert("RGB").save(output, format="PNG")
        return output.getvalue()

    def live_map(self):
        if self.pipeline is None:
            raise ApiUnavailableError("analysis pipeline is not configured")
        try:
            snapshot = self.pipeline.slam.snapshot()
        except Exception as error:
            raise ApiUnavailableError(str(error)) from error
        grid = snapshot.occupancy_grid
        return {
            "frame_id": grid.frame_id,
            "map_version": snapshot.map_version,
            "width": grid.width,
            "height": grid.height,
            "resolution": grid.resolution,
            "origin": grid.origin.to_dict(),
            "robot_pose": snapshot.robot_pose.to_dict(),
            "trajectory": [pose.to_dict() for pose in snapshot.trajectory],
        }

    def _candidates(self):
        if self.candidate_source is not None:
            return tuple(self.candidate_source())
        if (
            self.pipeline is not None
            and getattr(
                self.pipeline.slam.status().mode,
                "value",
                self.pipeline.slam.status().mode,
            )
            == ProviderMode.MOCK.value
        ):
            return deterministic_mock_candidates()
        return ()

    def _require_analysis_ready(self) -> None:
        if self.analysis_readiness is None:
            return
        try:
            self.analysis_readiness()
        except Exception as error:
            raise ApiUnavailableError(str(error)) from error

    def _write_preview(self, mission, *, artifact_version: int) -> dict[str, Any]:
        if self.pipeline is None:
            raise ApiUnavailableError("analysis pipeline is not configured")
        try:
            snapshot = self.pipeline.slam.snapshot()
        except Exception as error:
            raise ApiUnavailableError(str(error)) from error
        rendered = self.preview_renderer.render(
            snapshot,
            mission_id=mission.manifest.mission_id,
            base_map_version=mission.manifest.mission_version,
            artifact_version=artifact_version,
        )
        atomic_write_bytes(mission.directory / "map_preview.png", rendered.png)
        grid = snapshot.occupancy_grid
        alignment = (
            self.map_alignment_source(mission.manifest)
            if self.map_alignment_source is not None
            else None
        )
        metadata = {
            "mission_id": mission.manifest.mission_id,
            "base_map_version": mission.manifest.mission_version,
            "map_version": snapshot.map_version,
            "artifact_version": artifact_version,
            "frame_id": grid.frame_id,
            "coordinate_frame": "mission_map",
            "analysis_mode": self.mode,
            "resolution_m_per_cell": grid.resolution,
            "origin": grid.origin.to_dict(),
            "source_grid": {"width": grid.width, "height": grid.height},
            "preview": {"width": rendered.width, "height": rendered.height},
            "content_signature": rendered.content_signature,
            "map_alignment": alignment,
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
        preview = self._write_preview(mission, artifact_version=version)
        self.events.publish(
            "analysis.completed",
            {
                "mission_id": mission.manifest.mission_id,
                "result_version": version,
                "analysis_mode": result["analysis_mode"],
            },
        )
        return {
            "result": result,
            "analysis_mode": result["analysis_mode"],
            "unreachable_candidate_ids": list(report.unreachable_candidate_ids),
            "map_preview": preview,
        }

    def current_result(self):
        mission = self._mission()
        latest = self.manager.latest_result_version(
            mission.manifest.mission_id, mission.manifest.mission_version
        )
        if latest is None:
            raise ApiNotFoundError("no semantic result is stored")
        return {
            "result": self.manager.load_semantic_result(
                mission.manifest.mission_id, mission.manifest.mission_version, latest
            ),
            "state": "ready",
            "sendable": True,
        }

    def send_current_result(self, *, priority=0):
        mission = self._mission()
        result = self.current_result()["result"]
        path = mission.directory / f"semantic_result_v{result['result_version']}.json"
        transfer = (
            dict(self.transport.send_semantic_result(result, path, priority=priority))
            if self.transport
            else {
                "simulated": True,
                "state": "not_wired",
                "owner": "src/uwb",
                "priority": priority,
            }
        )
        return {"state": transfer.get("state", "submitted"), "transfer": transfer}

    def request_preview(self):
        if self.pipeline is None:
            raise ApiUnavailableError("analysis pipeline is not configured")
        mission = self._mission()
        latest = self.manager.latest_result_version(
            mission.manifest.mission_id, mission.manifest.mission_version
        )
        try:
            map_version = self.pipeline.slam.snapshot().map_version
        except Exception as error:
            raise ApiUnavailableError(str(error)) from error
        artifact_version = latest or max(1, map_version)
        return self._write_preview(mission, artifact_version=artifact_version)

    def current_preview(self):
        path = self._mission().directory / "map_preview.json"
        if not path.is_file():
            raise ApiNotFoundError("no map preview is stored")
        return json.loads(path.read_text())

    def current_preview_png(self):
        path = self._mission().directory / "map_preview.png"
        if not path.is_file():
            raise ApiNotFoundError("no map preview is stored")
        return path.read_bytes()

    def send_preview(self, *, priority=0):
        mission = self._mission()
        metadata = self.current_preview()
        path = mission.directory / "map_preview.png"
        transfer = (
            dict(self.transport.send_map_preview(metadata, path, priority=priority))
            if self.transport
            else {
                "simulated": True,
                "state": "not_wired",
                "owner": "src/uwb",
                "priority": priority,
            }
        )
        return {**metadata, "transfer": transfer}

    def current_approved_plan(self):
        path = self._mission().directory / "approved_plan.json"
        if not path.is_file():
            raise ApiNotFoundError("no approved plan is stored")
        return {"plan": json.loads(path.read_text())}
