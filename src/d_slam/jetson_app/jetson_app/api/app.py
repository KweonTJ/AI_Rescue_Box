from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..config import load_config
from ..map_preview import OccupancyPreviewRenderer
from ..mission import MissionManager
from ..rescue_map import SemanticRescueMapRenderer
from ..runtime import Stage3Runtime
from ..stage4 import Stage4Processor
from .service import (
    ApiConflictError,
    ApiNotFoundError,
    ApiUnavailableError,
    JetsonApiService,
)
from .stage4_service import Stage4JetsonApiService


class SendRequest(BaseModel):
    priority: int = Field(default=0, ge=0, le=255)


def create_app(service: JetsonApiService | None = None) -> FastAPI:
    runtime: Stage3Runtime | None = None
    if service is None:
        config = load_config()
        data_root = Path(
            os.environ.get("AI_RESCUE_DATA_ROOT", str(config.data_root))
        ).expanduser()
        runtime = Stage3Runtime(config)
        # Keep Stage3Runtime and all of its sensor providers intact. Stage 4
        # only injects map fusion/planning into the existing AnalysisPipeline.
        runtime.pipeline.stage4 = Stage4Processor(
            config.stage4,
            occupied_threshold=config.occupied_threshold,
            minimum_passage_width_m=config.minimum_passage_width_m,
        )
        service = Stage4JetsonApiService(
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
            mode=config.mode,
            provider_status_source=runtime.component_status,
            analysis_readiness=runtime.ensure_analysis_ready,
            mission_reset=runtime.reset_mission,
            map_alignment_source=runtime.map_alignment_for,
        )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if runtime is not None:
            runtime.start()
        try:
            yield
        finally:
            if runtime is not None:
                runtime.stop()

    app = FastAPI(
        title="AI Rescue Box Jetson API",
        version="1.0.0",
        lifespan=lifespan,
    )

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
    def health():
        return call(service.health)

    @app.get("/api/v1/status")
    def status():
        return call(service.status)

    @app.get("/api/v1/missions")
    def missions():
        return call(service.list_missions)

    @app.get("/api/v1/missions/current")
    def current_mission():
        return call(service.current_mission)

    @app.get("/api/v1/missions/{mission_id}/{mission_version}")
    def mission_detail(mission_id: str, mission_version: int):
        return call(service.mission_detail, mission_id, mission_version)

    @app.post("/api/v1/missions/{mission_id}/{mission_version}/select")
    def select_mission(mission_id: str, mission_version: int):
        return call(service.select_mission, mission_id, mission_version)

    @app.get("/api/v1/missions/{mission_id}/{mission_version}/base-map.png")
    def base_map(mission_id: str, mission_version: int):
        return Response(
            call(service.base_map_png, mission_id, mission_version),
            media_type="image/png",
        )

    @app.get("/api/v1/map/current")
    def live_map():
        return call(service.live_map)

    @app.post("/api/v1/analysis")
    def analyze():
        return call(service.analyze)

    @app.get("/api/v1/results/current")
    def result():
        return call(service.current_result)

    @app.post("/api/v1/results/current/send")
    def send_result(request: SendRequest = SendRequest()):
        return call(service.send_current_result, priority=request.priority)

    @app.post("/api/v1/preview")
    def preview():
        return call(service.request_preview)

    @app.get("/api/v1/preview/current")
    def current_preview():
        return call(service.current_preview)

    @app.get("/api/v1/preview/current.png")
    def preview_png():
        return Response(call(service.current_preview_png), media_type="image/png")

    @app.post("/api/v1/preview/send")
    def send_preview(request: SendRequest = SendRequest()):
        return call(service.send_preview, priority=request.priority)

    @app.get("/api/v1/approved-plan/current")
    def approved():
        return call(service.current_approved_plan)

    @app.websocket("/api/v1/events/ws")
    async def events(
        websocket: WebSocket,
        after_sequence: int = 0,
        instance_id: str | None = None,
    ) -> None:
        if after_sequence < 0:
            await websocket.close(code=1008, reason="after_sequence must be non-negative")
            return
        await websocket.accept()
        service.events.publish("events.connected", {"client": "tablet"})
        try:
            async for event in service.events.stream(
                after_sequence=after_sequence,
                instance_id=instance_id,
            ):
                await websocket.send_json(event)
        except WebSocketDisconnect:
            return

    return app
