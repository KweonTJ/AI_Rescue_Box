#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHONPATH="$ROOT/host_app${PYTHONPATH:+:$PYTHONPATH}" exec python3 -m host_app.api "$@"
