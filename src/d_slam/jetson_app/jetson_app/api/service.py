from __future__ import annotations
from pathlib import Path
from typing import Any
from ..analysis import AnalysisPipeline
from ..mission import MissionManager

class JetsonService:
    """Stage 1 local application service. No UWB implementation is wired here."""
    def __init__(self, manager: MissionManager, pipeline: AnalysisPipeline | None = None) -> None:
        self.manager=manager; self.pipeline=pipeline; self._selected: tuple[str,int]|None=None; self._current_result: dict[str,Any]|None=None
    def status(self) -> dict[str,Any]: return {"stage":"stage01","mission":self._selected,"analysis_ready":self.pipeline is not None,"uwb_wired":False}
    def list_missions(self): return [{"mission_id":m,"mission_version":v} for m,v in self.manager.list_missions()]
    def select_mission(self, mission_id: str, mission_version: int):
        mission=self.manager.load_mission(mission_id,mission_version); self._selected=(mission_id,mission_version); return mission.to_dict()
    def current_mission(self):
        if self._selected is None: return None
        return self.manager.load_mission(*self._selected).to_dict()
