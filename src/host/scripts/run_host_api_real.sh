#!/usr/bin/env bash
set -Eeuo pipefail
D="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$D/_runtime_env.sh"; activate_ros
mkdir -p "$AI_RESCUE_HOST_DATA"
exec python3 -m host_app.api --host "$AI_RESCUE_API_HOST" --port "$AI_RESCUE_API_PORT" --data-dir "$AI_RESCUE_HOST_DATA" --cors-origin "$AI_RESCUE_PUBLIC_ORIGIN" --cors-origin "$AI_RESCUE_LOCAL_ORIGIN" "$@"
