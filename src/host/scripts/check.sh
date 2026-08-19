#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="$(cd "$ROOT/../.." && pwd)"
python3 -m compileall -q "$ROOT/host_app"
python3 "$REPO/scripts/check_import_boundaries.py"
python3 -m pytest -q "$ROOT/tests"
find "$ROOT" -type f -name '*.sh' -print0 | xargs -0 -r -n1 bash -n
