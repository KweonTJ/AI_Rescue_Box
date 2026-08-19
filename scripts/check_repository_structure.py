#!/usr/bin/env python3
from __future__ import annotations
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; SRC=ROOT/'src'
EXPECTED={'host','uwb','d_slam'}
REQUIRED=(
'src/host/host_app','src/host/flutter_app/pubspec.yaml','src/host/flutter_app/lib','src/host/flutter_app/android','src/host/flutter_app/linux','src/host/flutter_app/web','src/host/flutter_app/test','src/host/ros2_ws/src/uwb_host_bridge','src/host/tests',
'src/uwb/protocol','src/uwb/runtime','src/uwb/interfaces','src/uwb/ros2_ws','src/uwb/firmware','src/uwb/tests',
'src/d_slam/astra_camera','src/d_slam/astra_camera_msgs','src/d_slam/d_slam','src/d_slam/jetson_app','src/d_slam/flutter_app/pubspec.yaml','src/d_slam/tests')
FORBIDDEN=(
'common',
'.stage01_payload',
'.github/workflows/apply-stage01-temp.yml',
'src/host/'+'prepare_from_'+'rescue'+'_app.sh',
'src/uwb/'+'prepare_from_'+'rescue'+'_app.sh',
)
SCHEMAS=('mission_manifest.schema.json','semantic_result.schema.json','approved_plan.schema.json','map_delta.schema.json','urgent_event.schema.json')

def main():
    errors=[]
    actual={p.name for p in SRC.iterdir() if p.is_dir()} if SRC.is_dir() else set()
    if actual!=EXPECTED: errors.append(f"src direct children must be {sorted(EXPECTED)}, got {sorted(actual)}")
    for rel in REQUIRED:
        if not (ROOT/rel).exists(): errors.append(f"missing required path: {rel}")
    for rel in FORBIDDEN:
        if (ROOT/rel).exists(): errors.append(f"forbidden path remains: {rel}")
    schema_root=ROOT/'src/uwb/interfaces/schemas'
    for name in SCHEMAS:
        path=schema_root/name
        if not path.is_file(): errors.append(f"missing schema: {name}"); continue
        try: value=json.loads(path.read_text(encoding='utf-8'))
        except Exception as error: errors.append(f"invalid schema {name}: {error}"); continue
        if value.get('$schema')!='https://json-schema.org/draft/2020-12/schema': errors.append(f"unexpected schema draft: {name}")
    if errors:
        print('Repository structure check failed:',file=sys.stderr)
        for error in errors: print(f' - {error}',file=sys.stderr)
        return 1
    print('Repository structure check passed'); return 0
if __name__=='__main__': raise SystemExit(main())
