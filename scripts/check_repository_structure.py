#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'src'
expected={'host','uwb','d_slam'}
actual={p.name for p in SRC.iterdir() if p.is_dir()}
errors=[]
if actual != expected: errors.append(f"src direct children: expected={sorted(expected)} actual={sorted(actual)}")
required=[
 'src/host/host_app','src/host/flutter_app/pubspec.yaml','src/host/ros2_ws/src/uwb_host_bridge',
 'src/uwb/protocol','src/uwb/runtime','src/uwb/interfaces','src/uwb/ros2_ws','src/uwb/firmware',
 'src/d_slam/astra_camera','src/d_slam/astra_camera_msgs','src/d_slam/d_slam','src/d_slam/jetson_app','src/d_slam/flutter_app/pubspec.yaml',
]
for rel in required:
    if not (ROOT/rel).exists(): errors.append(f"missing required path: {rel}")
for rel in ['common','.stage01_'+'payload','.github/workflows/'+'apply-stage01-temp.yml']:
    if (ROOT/rel).exists(): errors.append(f"forbidden path exists: {rel}")
for rel in ['src/host/'+'prepare_from_'+'rescue'+'_app.sh','src/uwb/'+'prepare_from_'+'rescue'+'_app.sh']:
    if (ROOT/rel).exists(): errors.append(f"forbidden preparation script exists: {rel}")
contract=ROOT/'src/uwb/interfaces'
for name in ['mission_manifest.schema.json','semantic_result.schema.json','approved_plan.schema.json','map_delta.schema.json','urgent_event.schema.json']:
    if not (contract/'schemas'/name).is_file(): errors.append(f"missing schema: {name}
")
for name in ['LoadMission.srv','ApplyApprovedPlan.srv','MissionControl.srv']:
    if not any(contract.rglob(name)): errors.append(f"missing ROS service: {name}")
if not any(contract.rglob('SubmitRescueUpdate.action')): errors.append('missing ROS action: SubmitRescueUpdate.action')
if errors:
    print('\n'.join(errors)); sys.exit(1)
print('repository structure: OK')
