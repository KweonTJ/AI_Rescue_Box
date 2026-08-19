#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 -m compileall -q "$ROOT/protocol" "$ROOT/runtime"
if command -v colcon >/dev/null 2>&1 && [[ -n "${ROS_DISTRO:-}" ]]; then (cd "$ROOT/ros2_ws" && colcon build); fi
