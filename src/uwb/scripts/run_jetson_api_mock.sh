#!/usr/bin/env bash
set -Eeuo pipefail
D="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$D/_runtime_env.sh"; activate_runtime
exec python3 -m jetson_app.api --mock --no-ros --host "$AI_RESCUE_API_HOST" --port "$AI_RESCUE_API_PORT" --cors-origin "$AI_RESCUE_PUBLIC_ORIGIN" --cors-origin "$AI_RESCUE_LOCAL_ORIGIN" "$@"
