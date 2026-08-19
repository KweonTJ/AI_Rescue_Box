#!/usr/bin/env python3
from __future__ import annotations
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src/host/host_app'));sys.path.insert(0,str(ROOT/'src/d_slam/jetson_app'))
from host_app.mission.models import SemanticResult as HostSemanticResult
from jetson_app.domain import Pose2D, SemanticResult as JetsonSemanticResult
from jetson_app.mission.artifacts import validate_semantic_result as validate_jetson_artifact
REQUIRED={'schema_version','mission_id','base_map_version','slam_map_version','result_version','artifact_version','created_at','coordinate_frame','units','source','confidence','robot_pose','robot_trajectory','victim_candidates','confirmed_victims','obstacles','risk_zones','entry_routes','team_recommendations','safe_waiting_points','explored_areas','unknown_areas'}
def main():
    schema=json.loads((ROOT/'src/uwb/interfaces/schemas/semantic_result.schema.json').read_text())
    if set(schema.get('required',()))!=REQUIRED: raise SystemExit(f"semantic_result required fields differ: {sorted(set(schema.get('required',()))^REQUIRED)}")
    properties=schema.get('properties',{})
    if properties.get('coordinate_frame',{}).get('const')!='mission_map': raise SystemExit('semantic_result coordinate_frame must be mission_map')
    if not {'real','mock','unknown'}<=set(properties.get('analysis_mode',{}).get('enum',())): raise SystemExit('analysis_mode must allow real, mock and unknown')
    payload=JetsonSemanticResult(mission_id='contract-check',base_map_version=1,result_version=1,coordinate_frame='mission_map',robot_pose=Pose2D(0,0,0),trajectory=(),victim_candidates=(),risks=(),routes=(),recommendations=(),slam_map_version=1).to_dict()
    missing=REQUIRED-set(payload)
    if missing: raise SystemExit(f"d_slam serializer missing: {sorted(missing)}")
    if payload.get('analysis_mode') not in {'real','mock'}: raise SystemExit('d_slam serializer must explicitly emit real or mock')
    host=HostSemanticResult.validate(payload,'contract-check'); jetson=validate_jetson_artifact(payload,'contract-check')
    if host.get('analysis_mode')!=payload['analysis_mode'] or jetson.get('analysis_mode')!=payload['analysis_mode']: raise SystemExit('analysis_mode not preserved by validators')
    optional=dict(payload); optional.pop('analysis_mode')
    if validate_jetson_artifact(optional,'contract-check').get('analysis_mode')!='unknown': raise SystemExit('optional analysis_mode must normalize to unknown')
    print('contract alignment: OK'); return 0
if __name__=='__main__': raise SystemExit(main())
