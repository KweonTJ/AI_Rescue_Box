#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DSLAM_ROOT="$ROOT/src/d_slam"

export AI_RESCUE_JETSON_API_HOST="${AI_RESCUE_JETSON_API_HOST:-0.0.0.0}"
export AI_RESCUE_JETSON_API_PORT="${AI_RESCUE_JETSON_API_PORT:-8001}"
export AI_RESCUE_DATA_ROOT="${AI_RESCUE_DATA_ROOT:-$ROOT/data/jetson}"
mkdir -p "$AI_RESCUE_DATA_ROOT"

printf 'Jetson API bind: %s:%s\n' "$AI_RESCUE_JETSON_API_HOST" "$AI_RESCUE_JETSON_API_PORT"
printf 'Jetson data root: %s\n' "$AI_RESCUE_DATA_ROOT"

exec "$DSLAM_ROOT/scripts/run_api.sh"
