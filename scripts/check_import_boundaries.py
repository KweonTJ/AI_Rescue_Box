#!/usr/bin/env python3
from pathlib import Path
import ast, sys
ROOT=Path(__file__).resolve().parents[1]
violations=[]

def imports(path: Path):
    try: tree=ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    except (UnicodeDecodeError,SyntaxError): return []
    result=[]
    for node in ast.walk(tree):
        if isinstance(node,ast.Import): result += [alias.name for alias in node.names]
        elif isinstance(node,ast.ImportFrom) and node.module: result.append(node.module)
    return result

for path in (ROOT/'src/d_slam').rglob('*.py'):
    for name in imports(path):
        if name.startswith(('src.uwb.runtime','src.uwb.protocol','uwb.runtime','uwb.protocol','ai_rescue_uwb_common')): violations.append((path,name))
for path in (ROOT/'src/uwb').rglob('*.py'):
    for name in imports(path):
        if name.startswith(('src.d_slam','d_slam.','jetson_app')): violations.append((path,name))
for path in (ROOT/'src/host').rglob('*.py'):
    for name in imports(path):
        if name.startswith(('src.d_slam','d_slam.','jetson_app')): violations.append((path,name))
if violations:
    for path,name in violations: print(f"boundary violation: {path.relative_to(ROOT)} -> {name}")
    sys.exit(1)
print('import boundaries: OK')
