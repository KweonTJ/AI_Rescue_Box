#!/usr/bin/env python3
from pathlib import Path
import argparse, subprocess
p=argparse.ArgumentParser(); p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]); root=p.parse_args().root.resolve()
required=['README.md','requirements.txt','config/host.env.example','host_app/pyproject.toml','host_app/host_app/api/__main__.py','host_app/flutter_app/pubspec.yaml','flutter_shared/pubspec.yaml','common/ai_rescue_uwb_common/bridge.py','ros2_ws/src/uwb_interfaces/package.xml','ros2_ws/src/uwb_host_bridge/uwb_host_bridge/node.py']
missing=[x for x in required if not (root/x).is_file()]
if missing: raise SystemExit('[FAIL] run prepare_from_rescue_app.sh; missing: '+', '.join(missing))
for s in list((root/'scripts').glob('*.sh'))+[root/'prepare_from_rescue_app.sh']:
    if subprocess.run(['bash','-n',str(s)]).returncode: raise SystemExit(f'[FAIL] Bash syntax: {s}')
print('[PASS] Host Flutter/UWB package structure is valid')
