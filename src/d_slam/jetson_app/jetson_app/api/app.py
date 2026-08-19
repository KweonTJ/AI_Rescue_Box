from __future__ import annotations

import os
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..mission import MissionManager
from .service import ApiConflictError, ApiNotFoundError, ApiUnavailableError, JetsonApiService

class SendRequest(BaseModel): priority: int = Field(default=0, ge=0, le=255)

def create_app(service: JetsonApiService | None = None) -> FastAPI:
    if service is None:
        root=Path(os.environ.get('AI_RESCUE_DATA_ROOT','data'))
        service=JetsonApiService(MissionManager(root/'missions'))
    app=FastAPI(title='AI Rescue Box Jetson API',version='1.0.0')
    def call(function,*args,**kwargs):
        try: return function(*args,**kwargs)
        except ApiNotFoundError as error: raise HTTPException(404,str(error)) from error
        except ApiConflictError as error: raise HTTPException(409,str(error)) from error
        except ApiUnavailableError as error: raise HTTPException(503,str(error)) from error
        except (ValueError,OSError,RuntimeError) as error: raise HTTPException(422,str(error)) from error
    @app.get('/api/v1/health')
    def health(): return call(service.health)
    @app.get('/api/v1/status')
    def status(): return call(service.status)
    @app.get('/api/v1/missions')
    def missions(): return call(service.list_missions)
    @app.get('/api/v1/missions/current')
    def current_mission(): return call(service.current_mission)
    @app.get('/api/v1/missions/{mission_id}/{mission_version}')
    def mission_detail(mission_id:str,mission_version:int): return call(service.mission_detail,mission_id,mission_version)
    @app.post('/api/v1/missions/{mission_id}/{mission_version}/select')
    def select_mission(mission_id:str,mission_version:int): return call(service.select_mission,mission_id,mission_version)
    @app.get('/api/v1/missions/{mission_id}/{mission_version}/base-map.png')
    def base_map(mission_id:str,mission_version:int): return Response(call(service.base_map_png,mission_id,mission_version),media_type='image/png')
    @app.get('/api/v1/map/current')
    def live_map(): return call(service.live_map)
    @app.post('/api/v1/analysis')
    def analyze(): return call(service.analyze)
    @app.get('/api/v1/results/current')
    def result(): return call(service.current_result)
    @app.post('/api/v1/results/current/send')
    def send_result(request:SendRequest=SendRequest()): return call(service.send_current_result,priority=request.priority)
    @app.post('/api/v1/preview')
    def preview(): return call(service.request_preview)
    @app.get('/api/v1/preview/current')
    def current_preview(): return call(service.current_preview)
    @app.get('/api/v1/preview/current.png')
    def preview_png(): return Response(call(service.current_preview_png),media_type='image/png')
    @app.post('/api/v1/preview/send')
    def send_preview(request:SendRequest=SendRequest()): return call(service.send_preview,priority=request.priority)
    @app.get('/api/v1/approved-plan/current')
    def approved(): return call(service.current_approved_plan)
    return app
