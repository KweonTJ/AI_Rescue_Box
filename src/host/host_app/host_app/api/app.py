"""FastAPI transport for the Host domain service."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import (
    FastAPI,
    HTTPException,
    Path as ApiPath,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from ..errors import StaleVersionError, ValidationError
from .schemas import MissionCreateRequest, PlanBuildRequest, ReviewCommandRequest
from .service import HostApiService, ResourceNotFoundError


API_PREFIX = "/api/v1"
PositiveVersion = Annotated[int, ApiPath(ge=1)]


def _configured_origins(value: list[str] | tuple[str, ...] | None) -> list[str]:
    if value is not None:
        return [item.strip() for item in value if item.strip()]
    raw = os.environ.get("AI_RESCUE_API_CORS_ORIGINS", "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def create_app(
    service: HostApiService | None = None,
    *,
    data_root: Path | None = None,
    cors_origins: list[str] | tuple[str, ...] | None = None,
) -> FastAPI:
    """Create an app around an injected service; no ROS/serial import occurs here."""

    owns_service = service is None
    if service is None:
        service = HostApiService(data_root or Path.cwd() / "data")

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        yield
        if owns_service:
            application.state.host_service.close()

    app = FastAPI(
        title="AI Rescue Box Host API",
        version="1.0.0",
        description=(
            "Local Host orchestration API. Clients never access ROS2 or serial "
            "transports directly."
        ),
        lifespan=lifespan,
    )
    app.state.host_service = service
    origins = _configured_origins(cors_origins)
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Content-Type", "Authorization"],
        )

    @app.exception_handler(StaleVersionError)
    async def stale_version_handler(
        request: Request, error: StaleVersionError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": str(error), "code": "version_conflict"},
        )

    @app.exception_handler(ResourceNotFoundError)
    async def not_found_handler(
        request: Request, error: ResourceNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": str(error), "code": "not_found"},
        )

    @app.exception_handler(ValidationError)
    async def validation_handler(
        request: Request, error: ValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": str(error), "code": "domain_validation"},
        )

    def current_service() -> HostApiService:
        return app.state.host_service

    @app.get(f"{API_PREFIX}/health", tags=["system"])
    async def health() -> dict:
        return current_service().health()

    @app.get(f"{API_PREFIX}/status", tags=["system"])
    async def host_status() -> dict:
        return current_service().status()

    @app.get(f"{API_PREFIX}/operations/{{operation_id}}", tags=["operations"])
    async def operation(operation_id: str) -> dict:
        return current_service().get_operation(operation_id)

    @app.post(f"{API_PREFIX}/status/reconnect", tags=["system"])
    async def reconnect() -> dict:
        accepted = await asyncio.to_thread(current_service().reconnect_bridge)
        return {"accepted": accepted}

    @app.post(
        f"{API_PREFIX}/maps",
        status_code=status.HTTP_201_CREATED,
        tags=["maps"],
        summary="Upload raw JPEG/PNG bytes",
    )
    async def upload_map(
        request: Request,
        filename: Annotated[str, Query(min_length=1, max_length=255)],
    ) -> dict:
        media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if media_type != "application/octet-stream":
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Content-Type must be application/octet-stream",
            )
        service_value = current_service()
        declared_length = request.headers.get("content-length")
        if declared_length is not None:
            try:
                parsed_length = int(declared_length)
                if parsed_length < 0:
                    raise ValueError
                if parsed_length > service_value.normalization_options.max_input_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="map upload exceeds the configured size limit",
                    )
            except ValueError as error:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Content-Length must be an integer",
                ) from error
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > service_value.normalization_options.max_input_bytes:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="map upload exceeds the configured size limit",
                )
        return await asyncio.to_thread(
            service_value.upload_map, filename, bytes(content)
        )

    upload_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == f"{API_PREFIX}/maps"
        and "POST" in getattr(route, "methods", set())
    )
    upload_route.openapi_extra = {
        "requestBody": {
            "required": True,
            "content": {
                "application/octet-stream": {
                    "schema": {"type": "string", "format": "binary"}
                }
            },
        }
    }

    @app.get(f"{API_PREFIX}/maps", tags=["maps"])
    async def list_maps() -> dict:
        return {"items": await asyncio.to_thread(current_service().list_maps)}

    @app.get(f"{API_PREFIX}/maps/{{map_id}}", tags=["maps"])
    async def get_map(map_id: str) -> dict:
        return await asyncio.to_thread(current_service().get_map, map_id)

    @app.get(
        f"{API_PREFIX}/maps/{{map_id}}/content",
        response_class=FileResponse,
        tags=["maps"],
    )
    async def get_map_content(map_id: str) -> FileResponse:
        path = await asyncio.to_thread(current_service().uploaded_map_path, map_id)
        media_type = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        return FileResponse(path, media_type=media_type, filename=path.name)

    @app.post(
        f"{API_PREFIX}/missions",
        status_code=status.HTTP_201_CREATED,
        tags=["missions"],
    )
    async def create_mission(body: MissionCreateRequest) -> dict:
        return await asyncio.to_thread(
            current_service().create_mission, body.model_dump()
        )

    @app.get(f"{API_PREFIX}/missions", tags=["missions"])
    async def list_missions() -> dict:
        return {"items": await asyncio.to_thread(current_service().list_missions)}

    @app.get(
        f"{API_PREFIX}/missions/{{mission_id}}/{{mission_version}}",
        tags=["missions"],
    )
    async def get_mission(mission_id: str, mission_version: PositiveVersion) -> dict:
        return await asyncio.to_thread(
            current_service().get_mission, mission_id, mission_version
        )

    @app.post(
        f"{API_PREFIX}/missions/{{mission_id}}/{{mission_version}}/activate",
        tags=["missions"],
        summary="Select the persisted mission for inbound artifacts",
    )
    async def activate_mission(
        mission_id: str, mission_version: PositiveVersion
    ) -> dict:
        return await asyncio.to_thread(
            current_service().activate_mission, mission_id, mission_version
        )

    @app.get(
        f"{API_PREFIX}/missions/{{mission_id}}/{{mission_version}}/base-map",
        response_class=FileResponse,
        tags=["missions"],
    )
    async def mission_base_map(
        mission_id: str, mission_version: PositiveVersion
    ) -> FileResponse:
        path = await asyncio.to_thread(
            current_service().mission_base_map_path, mission_id, mission_version
        )
        media_type = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        return FileResponse(path, media_type=media_type, filename=path.name)

    @app.post(
        f"{API_PREFIX}/missions/{{mission_id}}/{{mission_version}}/send",
        status_code=status.HTTP_202_ACCEPTED,
        tags=["transfers"],
    )
    async def send_mission(mission_id: str, mission_version: PositiveVersion) -> dict:
        return await asyncio.to_thread(
            current_service().send_mission, mission_id, mission_version
        )

    @app.get(
        f"{API_PREFIX}/missions/{{mission_id}}/{{mission_version}}/results",
        tags=["results"],
    )
    async def list_results(mission_id: str, mission_version: PositiveVersion) -> dict:
        return {
            "items": await asyncio.to_thread(
                current_service().list_results, mission_id, mission_version
            )
        }

    @app.get(
        f"{API_PREFIX}/missions/{{mission_id}}/{{mission_version}}/results/{{result_version}}",
        tags=["results"],
    )
    async def get_result(
        mission_id: str,
        mission_version: PositiveVersion,
        result_version: PositiveVersion,
    ) -> dict:
        return await asyncio.to_thread(
            current_service().get_result,
            mission_id,
            mission_version,
            result_version,
        )

    @app.post(
        f"{API_PREFIX}/missions/{{mission_id}}/{{mission_version}}/results/{{result_version}}/load",
        tags=["reviews"],
    )
    async def load_result(
        mission_id: str,
        mission_version: PositiveVersion,
        result_version: PositiveVersion,
    ) -> dict:
        return await asyncio.to_thread(
            current_service().load_result,
            mission_id,
            mission_version,
            result_version,
        )

    @app.get(
        f"{API_PREFIX}/missions/{{mission_id}}/{{mission_version}}/reviews/{{result_version}}",
        tags=["reviews"],
    )
    async def get_review(
        mission_id: str,
        mission_version: PositiveVersion,
        result_version: PositiveVersion,
    ) -> dict:
        return await asyncio.to_thread(
            current_service().review_state,
            mission_id,
            mission_version,
            result_version,
        )

    @app.post(
        f"{API_PREFIX}/missions/{{mission_id}}/{{mission_version}}/reviews/{{result_version}}/commands",
        tags=["reviews"],
    )
    async def review_command(
        mission_id: str,
        mission_version: PositiveVersion,
        result_version: PositiveVersion,
        body: ReviewCommandRequest,
    ) -> dict:
        return await asyncio.to_thread(
            current_service().apply_review_command,
            mission_id,
            mission_version,
            result_version,
            body.command,
            body.arguments,
            body.expected_revision,
        )

    @app.post(
        f"{API_PREFIX}/missions/{{mission_id}}/{{mission_version}}/reviews/{{result_version}}/plans",
        status_code=status.HTTP_201_CREATED,
        tags=["plans"],
    )
    async def build_plan(
        mission_id: str,
        mission_version: PositiveVersion,
        result_version: PositiveVersion,
        body: PlanBuildRequest,
    ) -> dict:
        return await asyncio.to_thread(
            current_service().build_approved_plan,
            mission_id,
            mission_version,
            result_version,
            body.plan_version,
            body.modified_at,
            body.expected_revision,
        )

    @app.get(
        f"{API_PREFIX}/missions/{{mission_id}}/{{mission_version}}/reviews/{{result_version}}/plans",
        tags=["plans"],
    )
    async def list_plans(
        mission_id: str,
        mission_version: PositiveVersion,
        result_version: PositiveVersion,
    ) -> dict:
        return await asyncio.to_thread(
            current_service().list_approved_plans,
            mission_id,
            mission_version,
            result_version,
        )

    @app.get(
        f"{API_PREFIX}/missions/{{mission_id}}/{{mission_version}}/reviews/{{result_version}}/plans/current",
        tags=["plans"],
    )
    async def current_plan(
        mission_id: str,
        mission_version: PositiveVersion,
        result_version: PositiveVersion,
    ) -> dict:
        return await asyncio.to_thread(
            current_service().current_approved_plan,
            mission_id,
            mission_version,
            result_version,
        )

    @app.post(
        f"{API_PREFIX}/missions/{{mission_id}}/{{mission_version}}/reviews/{{result_version}}/plans/{{plan_version}}/send",
        status_code=status.HTTP_202_ACCEPTED,
        tags=["transfers"],
    )
    async def send_plan(
        mission_id: str,
        mission_version: PositiveVersion,
        result_version: PositiveVersion,
        plan_version: PositiveVersion,
    ) -> dict:
        return await asyncio.to_thread(
            current_service().send_approved_plan,
            mission_id,
            mission_version,
            result_version,
            plan_version,
        )

    @app.get(
        f"{API_PREFIX}/missions/{{mission_id}}/{{mission_version}}/previews",
        tags=["results"],
    )
    async def list_previews(mission_id: str, mission_version: PositiveVersion) -> dict:
        return {
            "versions": await asyncio.to_thread(
                current_service().list_previews, mission_id, mission_version
            )
        }

    @app.get(
        f"{API_PREFIX}/missions/{{mission_id}}/{{mission_version}}/previews/{{preview_version}}",
        response_class=FileResponse,
        tags=["results"],
    )
    async def get_preview(
        mission_id: str,
        mission_version: PositiveVersion,
        preview_version: PositiveVersion,
    ) -> FileResponse:
        path = await asyncio.to_thread(
            current_service().preview_path,
            mission_id,
            mission_version,
            preview_version,
        )
        return FileResponse(path, media_type="image/png", filename=path.name)

    @app.get(
        f"{API_PREFIX}/missions/{{mission_id}}/{{mission_version}}/previews/"
        "{preview_version}/metadata",
        tags=["results"],
    )
    async def get_preview_metadata(
        mission_id: str,
        mission_version: PositiveVersion,
        preview_version: PositiveVersion,
    ) -> dict:
        return await asyncio.to_thread(
            current_service().preview_metadata,
            mission_id,
            mission_version,
            preview_version,
        )

    @app.websocket(f"{API_PREFIX}/events/ws")
    async def events(
        websocket: WebSocket,
        after_sequence: int = 0,
        instance_id: str | None = None,
    ) -> None:
        origin = websocket.headers.get("origin")
        if origin and origins and "*" not in origins and origin not in origins:
            await websocket.close(code=1008, reason="WebSocket origin is not allowed")
            return
        if after_sequence < 0:
            await websocket.close(code=1008, reason="after_sequence must be non-negative")
            return
        await websocket.accept()
        try:
            async for event in current_service().events.stream(
                after_sequence=after_sequence,
                instance_id=instance_id,
            ):
                await websocket.send_json(event)
        except WebSocketDisconnect:
            return

    return app


__all__ = ["API_PREFIX", "create_app"]
