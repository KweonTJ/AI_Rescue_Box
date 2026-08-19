#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHONPATH="$ROOT/jetson_app${PYTHONPATH:+:$PYTHONPATH}" exec python3 -m jetson_app.api
