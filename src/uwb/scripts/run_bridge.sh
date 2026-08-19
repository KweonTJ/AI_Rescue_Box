#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/protocol:$ROOT/ros2_ws/src/uwb_jetson_bridge${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m uwb_jetson_bridge.node "$@"
