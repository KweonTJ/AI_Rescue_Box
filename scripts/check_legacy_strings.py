#!/usr/bin/env python3
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
terms=[
 'prepare_from_'+'rescue'+'_app',
 'RESCUE'+'_APP_ROOT',
 '~/'+'rescue'+'_app',
 'rescue'+'_app/',
 'common/'+'ai_boost',
 'common/'+'contracts',
 'common/'+'flutter_shared',
 'oai'+'usercontent.com',
]
violations=[]
for path in ROOT.rglob('*'):
    if not path.is_file() or '.git' in path.parts: continue
    try: text=path.read_text(encoding='utf-8')
    except (UnicodeDecodeError,OSError): continue
    for term in terms:
        if term in text: violations.append((path.relative_to(ROOT),term))
if violations:
    for path,term in violations: print(f"legacy string: {path}: {term}")
    sys.exit(1)
print('legacy strings: OK')
