#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 -m compileall -q "$ROOT/host_app"
if command -v flutter >/dev/null 2>&1; then (cd "$ROOT/flutter_app" && flutter analyze && flutter test); fi
if command -v colcon >/dev/null 2>&1 && [[ -n "${ROS_DISTRO:-}" ]]; then (cd "$ROOT/ros2_ws" && colcon build); fi
