#!/usr/bin/env bash
set -Eeuo pipefail
D="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$D/_runtime_env.sh"; activate_runtime
CFG="${AI_RESCUE_JETSON_CONFIG:-$UWB_ROOT/jetson_app/config/default.yaml}"
exec python3 -m jetson_app.api --config "$CFG" --host "$AI_RESCUE_API_HOST" --port "$AI_RESCUE_API_PORT" --cors-origin "$AI_RESCUE_PUBLIC_ORIGIN" --cors-origin "$AI_RESCUE_LOCAL_ORIGIN" "$@"
