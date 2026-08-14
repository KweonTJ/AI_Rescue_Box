#!/usr/bin/env bash
set -Eeuo pipefail
D="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$D/_runtime_env.sh"; activate_ros
python3 "$HOST_ROOT/scripts/verify_package.py" --root "$HOST_ROOT"
python3 -m host_app.api --check
ros2 run uwb_host_bridge host_bridge --self-test
python3 -m serial.tools.list_ports -v || true
