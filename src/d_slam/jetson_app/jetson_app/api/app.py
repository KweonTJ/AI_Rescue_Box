from __future__ import annotations
from pathlib import Path
from .service import JetsonService
from ..mission import MissionManager

def create_app(service: JetsonService | None = None):
    try:
        from fastapi import FastAPI, HTTPException
    except ImportError as error:
        raise RuntimeError("FastAPI extra is required to create the HTTP app") from error
    app=FastAPI(title="AI Rescue Box Jetson API",version="0.1.0")
    service=service or JetsonService(MissionManager(Path("data/missions")))
    @app.get("/api/v1/health")
    def health(): return {"status":"ok","stage":"stage01"}
    @app.get("/api/v1/status")
    def status(): return service.status()
    @app.get("/api/v1/missions")
    def missions(): return {"items":service.list_missions()}
    @app.get("/api/v1/missions/current")
    def current():
        value=service.current_mission()
        if value is None: raise HTTPException(status_code=404,detail="no mission selected")
        return value
    @app.post("/api/v1/missions/{mission_id}/{mission_version}/select")
    def select(mission_id: str, mission_version: int):
        try: return service.select_mission(mission_id,mission_version)
        except Exception as error: raise HTTPException(status_code=400,detail=str(error)) from error
    return app
