#!/usr/bin/env bash
set -Eeuo pipefail
D="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$D/_runtime_env.sh"
cd "$UWB_ROOT/jetson_app/flutter_app"; flutter pub get
exec flutter run -d web-server --web-hostname 0.0.0.0 --web-port "$AI_RESCUE_FLUTTER_PORT" --dart-define="API_BASE_URL=$AI_RESCUE_API_BASE_URL" "$@"
