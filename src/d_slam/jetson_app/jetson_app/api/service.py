from __future__ import annotations

import asyncio, json, threading
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


class ApiNotFoundError(LookupError): pass
class ApiConflictError(RuntimeError): pass
class ApiUnavailableError(RuntimeError): pass


class JetsonApiService:
    def __init__(self, manager: MissionManager, *, pipeline: AnalysisPipeline|None=None, preview_renderer: OccupancyPreviewRenderer|None=None, candidate_source: Callable[[],Sequence[PersonCandidate]]|None=None, transport: ArtifactTransportPort|None=None, mode: str|None=None, events: EventHub|None=None):
        self.manager=manager; self.pipeline=pipeline; self.preview_renderer=preview_renderer or OccupancyPreviewRenderer(); self.candidate_source=candidate_source; self.transport=transport; self._mode=mode; self.events=events or EventHub(); self._selected=None; self._lock=threading.RLock()
    async def execute(self, function, *args, **kwargs): return await asyncio.to_thread(function,*args,**kwargs)
    @property
    def mode(self):
        if self._mode in {'real','mock'}: return self._mode
        if self.pipeline is not None and getattr(self.pipeline.slam.status().mode,'value',self.pipeline.slam.status().mode)==ProviderMode.MOCK.value: return 'mock'
        return 'real'
    def _selected_ref(self):
        selected=self.manager.current_mission_ref()
        with self._lock: self._selected=selected
        return selected
    def health(self): return {'status':'ok','stage':'stage01','mode':self.mode,'analysis_ready':self.pipeline is not None,'transport_wired':self.transport is not None}
    def status(self):
        slam={'name':'SLAM','mode':'unavailable','connected':False,'message':'analysis pipeline is not configured'}
        if self.pipeline is not None:
            state=self.pipeline.slam.status(); slam={'name':state.name,'mode':getattr(state.mode,'value',state.mode),'connected':state.connected,'message':state.message}
        uwb=dict(self.transport.status()) if self.transport is not None else {'name':'UWB transport','mode':'not_wired','connected':False,'message':'communication is owned by src/uwb'}
        return {'stage':'stage01','mode':self.mode,'current_mission':self._selected_ref(),'providers':{'slam':slam,'uwb':uwb},'runtime':{'analysis_ready':self.pipeline is not None,'transport_wired':self.transport is not None}}
    def list_missions(self):
        selected=self._selected_ref(); return [{'mission_id':mid,'mission_version':ver,'active':selected==(mid,ver)} for mid,ver in self.manager.list_missions()]
    def mission_detail(self, mission_id, mission_version):
        try: applied=self.manager.load_mission(mission_id,mission_version)
        except (ValidationError,OSError) as error: raise ApiNotFoundError(str(error)) from error
        return {'mission_id':mission_id,'mission_version':mission_version,'manifest':applied.manifest.to_dict(),'base_map':{'filename':applied.base_map_path.name,'download_url':f'/api/v1/missions/{mission_id}/{mission_version}/base-map.png'}}
    def select_mission(self, mission_id, mission_version):
        result=self.mission_detail(mission_id,mission_version); selected=self.manager.set_current_mission(mission_id,mission_version)
        with self._lock: self._selected=selected
        self.events.publish('mission.selected',{'mission_id':mission_id,'mission_version':mission_version}); return result
    def current_mission(self):
        selected=self._selected_ref()
        if selected is None: raise ApiNotFoundError('no mission is selected')
        return self.mission_detail(*selected)
    def _mission(self):
        selected=self._selected_ref()
        if selected is None: raise ApiConflictError('select a mission first')
        return self.manager.load_mission(*selected)
    def base_map_png(self, mission_id, mission_version):
        import io
        applied=self.manager.load_mission(mission_id,mission_version); out=io.BytesIO()
        with Image.open(applied.base_map_path) as image: image.convert('RGB').save(out,format='PNG')
        return out.getvalue()
    def live_map(self):
        if self.pipeline is None: raise ApiUnavailableError('analysis pipeline is not configured')
        snap=self.pipeline.slam.snapshot(); grid=snap.occupancy_grid
        return {'frame_id':grid.frame_id,'map_version':snap.map_version,'width':grid.width,'height':grid.height,'resolution':grid.resolution,'origin':grid.origin.to_dict(),'robot_pose':snap.robot_pose.to_dict(),'trajectory':[p.to_dict() for p in snap.trajectory]}
    def _candidates(self):
        if self.candidate_source is not None: return tuple(self.candidate_source())
        if self.pipeline is not None and getattr(self.pipeline.slam.status().mode,'value',self.pipeline.slam.status().mode)==ProviderMode.MOCK.value: return deterministic_mock_candidates()
        return ()
    def analyze(self):
        if self.pipeline is None: raise ApiUnavailableError('analysis pipeline is not configured')
        mission=self._mission(); version=(self.manager.latest_result_version(mission.manifest.mission_id,mission.manifest.mission_version) or 0)+1
        report=self.pipeline.run(mission=mission.manifest,candidates=self._candidates(),result_version=version,priorities={}); result=report.result.to_dict(); self.manager.save_semantic_result(mission.manifest.mission_id,mission.manifest.mission_version,result); return {'result':result,'analysis_mode':result['analysis_mode'],'unreachable_candidate_ids':list(report.unreachable_candidate_ids)}
    def current_result(self):
        mission=self._mission(); latest=self.manager.latest_result_version(mission.manifest.mission_id,mission.manifest.mission_version)
        if latest is None: raise ApiNotFoundError('no semantic result is stored')
        return {'result':self.manager.load_semantic_result(mission.manifest.mission_id,mission.manifest.mission_version,latest),'state':'ready','sendable':True}
    def send_current_result(self, *, priority=0):
        mission=self._mission(); result=self.current_result()['result']; path=mission.directory/f"semantic_result_v{result['result_version']}.json"
        transfer=dict(self.transport.send_semantic_result(result,path,priority=priority)) if self.transport else {'simulated':True,'state':'not_wired','owner':'src/uwb','priority':priority}
        return {'state':transfer.get('state','submitted'),'transfer':transfer}
    def request_preview(self):
        if self.pipeline is None: raise ApiUnavailableError('analysis pipeline is not configured')
        mission=self._mission(); snap=self.pipeline.slam.snapshot(); rendered=self.preview_renderer.render(snap,mission_id=mission.manifest.mission_id,base_map_version=mission.manifest.mission_version,artifact_version=snap.map_version); atomic_write_bytes(mission.directory/'map_preview.png',rendered.png); metadata={'mission_id':mission.manifest.mission_id,'base_map_version':mission.manifest.mission_version,'map_version':snap.map_version,'artifact_version':snap.map_version,'content_signature':rendered.content_signature,'download_url':'/api/v1/preview/current.png','state':'ready'}; atomic_write_json(mission.directory/'map_preview.json',metadata); return metadata
    def current_preview(self):
        path=self._mission().directory/'map_preview.json'
        if not path.is_file(): raise ApiNotFoundError('no map preview is stored')
        return json.loads(path.read_text())
    def current_preview_png(self):
        path=self._mission().directory/'map_preview.png'
        if not path.is_file(): raise ApiNotFoundError('no map preview is stored')
        return path.read_bytes()
    def send_preview(self, *, priority=0):
        mission=self._mission(); metadata=self.current_preview(); path=mission.directory/'map_preview.png'; transfer=dict(self.transport.send_map_preview(metadata,path,priority=priority)) if self.transport else {'simulated':True,'state':'not_wired','owner':'src/uwb','priority':priority}; return {**metadata,'transfer':transfer}
    def current_approved_plan(self):
        path=self._mission().directory/'approved_plan.json'
        if not path.is_file(): raise ApiNotFoundError('no approved plan is stored')
        return {'plan':json.loads(path.read_text())}
