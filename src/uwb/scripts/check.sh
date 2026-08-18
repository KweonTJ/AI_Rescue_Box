#!/usr/bin/env bash
set -Eeuo pipefail
D="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$D/_runtime_env.sh"; activate_runtime
python3 "$UWB_ROOT/scripts/verify_package.py" --root "$UWB_ROOT"
python3 -m jetson_app.api --help >/dev/null
ros2 run uwb_jetson_bridge jetson_bridge --self-test
python3 -m serial.tools.list_ports -v || true
