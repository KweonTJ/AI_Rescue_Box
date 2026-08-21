from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..config import load_config
from ..map_preview import OccupancyPreviewRenderer
from ..mission import MissionManager
from ..mission.tablet_ingest import TabletMissionIngestor
from ..rescue_map import SemanticRescueMapRenderer
from ..runtime import Stage3Runtime
from ..stage4 import Stage4Processor
from .continuous_service import ContinuousStage4JetsonApiService
from .service import ApiConflictError, ApiNotFoundError, ApiUnavailableError, JetsonApiService
from .uwb_transport import RosUwbArtifactTransport


class SendRequest(BaseModel):
    priority: int = Field(default=0, ge=0, le=255)


def create_app(service: JetsonApiService | None = None) -> FastAPI:
    runtime: Stage3Runtime | None = None
    if service is None:
        config = load_config()
        data_root = Path(os.environ.get("AI_RESCUE_DATA_ROOT", str(config.data_root))).expanduser()
        runtime = Stage3Runtime(config)
        runtime.pipeline.stage4 = Stage4Processor(
            config.stage4,
            occupied_threshold=config.occupied_threshold,
            minimum_passage_width_m=config.minimum_passage_width_m,
        )
        transport = None
        if runtime.sensor_node is not None:
            try:
                transport = RosUwbArtifactTransport(runtime.sensor_node)
            except RuntimeError:
                transport = None
        service = ContinuousStage4JetsonApiService(
            MissionManager(
                data_root / "missions",
                max_map_bytes=config.max_map_bytes,
                max_json_bytes=config.max_json_bytes,
            ),
            pipeline=runtime.pipeline,
            preview_renderer=OccupancyPreviewRenderer(
                occupied_threshold=config.occupied_threshold,
                max_dimension=config.map_preview_max_dimension,
            ),
            rescue_preview_renderer=SemanticRescueMapRenderer(
                max_dimension=config.map_preview_max_dimension,
                config=config.stage4,
            ),
            stage4_config=config.stage4,
            candidate_source=runtime.candidate_source,
            transport=transport,
            mode=config.mode,
            provider_status_source=runtime.component_status,
            analysis_readiness=runtime.ensure_analysis_ready,
            mission_reset=runtime.reset_mission,
            map_alignment_source=runtime.map_alignment_for,
        )

    tablet_ingestor = TabletMissionIngestor(service.manager)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if runtime is not None:
            runtime.start()
        start_monitor = getattr(service, "start_semantic_monitor", None)
        if callable(start_monitor):
            start_monitor()
        try:
            yield
        finally:
            stop_monitor = getattr(service, "stop_semantic_monitor", None)
            if callable(stop_monitor):
                stop_monitor()
            if runtime is not None:
                runtime.stop()

    app = FastAPI(title="AI Rescue Box Jetson API", version="1.0.0", lifespan=lifespan)

    def call(function, *args, **kwargs):
        try:
            return function(*args, **kwargs)
        except ApiNotFoundError as error:
            raise HTTPException(404, str(error)) from error
        except ApiConflictError as error:
            raise HTTPException(409, str(error)) from error
        except ApiUnavailableError as error:
            raise HTTPException(503, str(error)) from error
        except (ValueError, OSError, RuntimeError) as error:
            raise HTTPException(422, str(error)) from error

    @app.get("/api/v1/health")
    def health(): return call(service.health)

    @app.get("/api/v1/status")
    def status(): return call(service.status)

    @app.get("/api/v1/missions")
    def missions(): return call(service.list_missions)

    @app.get("/api/v1/missions/current")
    def current_mission(): return call(service.current_mission)

    @app.get("/api/v1/missions/{mission_id}/{mission_version}")
    def mission_detail(mission_id: str, mission_version: int):
        return call(service.mission_detail, mission_id, mission_version)

    @app.post("/api/v1/tablet/missions", status_code=201)
    async def create_tablet_mission(
        manifest: Annotated[str, Form()],
        base_map: Annotated[UploadFile | None, File()] = None,
        reuse_from_version: Annotated[int | None, Form()] = None,
    ):
        """Store a Tablet-authored Mission without making it ACTIVE.

        ``manifest`` is an image-space JSON draft.  ``base_map`` is required for
        a new Mission or when its image changes.  Existing Mission edits may
        omit it and reuse a prior version via ``reuse_from_version``.
        """

        try:
            draft = json.loads(manifest)
        except json.JSONDecodeError as error:
            raise HTTPException(422, "manifest form field must contain JSON") from error
        if not isinstance(draft, dict):
            raise HTTPException(422, "manifest form field must contain a JSON object")

        filename: str | None = None
        content: bytes | None = None
        if base_map is not None:
            filename = base_map.filename
            chunks = bytearray()
            try:
                while True:
                    chunk = await base_map.read(1024 * 1024)
                    if not chunk:
                        break
                    chunks.extend(chunk)
                    if len(chunks) > service.manager.max_map_bytes:
                        raise HTTPException(
                            413,
                            "Tablet base map exceeds the configured Mission size limit",
                        )
            finally:
                await base_map.close()
            content = bytes(chunks)

        def store():
            return call(
                tablet_ingestor.store,
                draft,
                base_map_filename=filename,
                base_map_bytes=content,
                reuse_from_version=reuse_from_version,
            )

        applied = await asyncio.to_thread(store)
        detail = call(
            service.mission_detail,
            applied.manifest.mission_id,
            applied.manifest.mission_version,
        )
        service.events.publish(
            "mission.stored",
            {
                "mission_id": applied.manifest.mission_id,
                "mission_version": applied.manifest.mission_version,
                "source": "tablet",
            },
        )
        return {
            **detail,
            "state": "STORED",
            "processing": {
                "state": "ready",
                "display_url": (
                    f"/api/v1/missions/{applied.manifest.mission_id}/"
                    f"{applied.manifest.mission_version}/display-map.png"
                ),
                "wall_mask_url": (
                    f"/api/v1/missions/{applied.manifest.mission_id}/"
                    f"{applied.manifest.mission_version}/wall-mask.png"
                ),
            },
        }

    @app.post("/api/v1/missions/{mission_id}/{mission_version}/select")
    def select_mission(mission_id: str, mission_version: int):
        return call(service.select_mission, mission_id, mission_version)

    @app.get("/api/v1/missions/{mission_id}/{mission_version}/base-map.png")
    def base_map(mission_id: str, mission_version: int):
        return Response(call(service.base_map_png, mission_id, mission_version), media_type="image/png")

    @app.get("/api/v1/missions/{mission_id}/{mission_version}/display-map.png")
    def display_map(mission_id: str, mission_version: int):
        # Older UWB-created Missions predate the derived display artifact.  They
        # remain usable by falling back to the canonical base-map conversion.
        call(service.mission_detail, mission_id, mission_version)
        path = service.manager.mission_directory(mission_id, mission_version) / "base_map_display.png"
        if path.is_file() and not path.is_symlink():
            return Response(path.read_bytes(), media_type="image/png")
        return Response(call(service.base_map_png, mission_id, mission_version), media_type="image/png")

    @app.get("/api/v1/missions/{mission_id}/{mission_version}/wall-mask.png")
    def wall_mask(mission_id: str, mission_version: int):
        call(service.mission_detail, mission_id, mission_version)
        path = service.manager.mission_directory(mission_id, mission_version) / "wall_mask.png"
        if not path.is_file() or path.is_symlink():
            raise HTTPException(404, "no processed wall mask is stored for this Mission")
        return Response(path.read_bytes(), media_type="image/png")

    @app.get("/api/v1/missions/{mission_id}/{mission_version}/processing")
    def processing(mission_id: str, mission_version: int):
        call(service.mission_detail, mission_id, mission_version)
        path = service.manager.mission_directory(mission_id, mission_version) / "processing.json"
        if not path.is_file() or path.is_symlink():
            raise HTTPException(404, "no processing metadata is stored for this Mission")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise HTTPException(422, "processing metadata is unreadable") from error
        if not isinstance(value, dict):
            raise HTTPException(422, "processing metadata is invalid")
        return value

    @app.get("/api/v1/map/current")
    def live_map(): return call(service.live_map)

    @app.post("/api/v1/analysis")
    def analyze(): return call(service.analyze)

    @app.get("/api/v1/results/current")
    def result(): return call(service.current_result)

    @app.post("/api/v1/results/current/send")
    def send_result(request: SendRequest = SendRequest()):
        return call(service.send_current_result, priority=request.priority)

    @app.post("/api/v1/preview")
    def preview(): return call(service.request_preview)

    @app.get("/api/v1/preview/current")
    def current_preview(): return call(service.current_preview)

    @app.get("/api/v1/preview/current.png")
    def preview_png(): return Response(call(service.current_preview_png), media_type="image/png")

    @app.post("/api/v1/preview/send")
    def send_preview(request: SendRequest = SendRequest()):
        return call(service.send_preview, priority=request.priority)

    @app.get("/api/v1/approved-plan/current")
    def approved(): return call(service.current_approved_plan)

    @app.websocket("/api/v1/events/ws")
    async def events(websocket: WebSocket, after_sequence: int = 0, instance_id: str | None = None) -> None:
        if after_sequence < 0:
            await websocket.close(code=1008, reason="after_sequence must be non-negative")
            return
        await websocket.accept()
        service.events.publish("events.connected", {"client": "tablet"})
        try:
            async for event in service.events.stream(after_sequence=after_sequence, instance_id=instance_id):
                await websocket.send_json(event)
        except WebSocketDisconnect:
            return

    return app
