#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 -m compileall -q "$ROOT/jetson_app" "$ROOT/d_slam"
if command -v flutter >/dev/null 2>&1; then (cd "$ROOT/flutter_app" && flutter analyze && flutter test); fi
if command -v colcon >/dev/null 2>&1 && [[ -n "${ROS_DISTRO:-}" ]]; then (cd "$ROOT" && colcon build --base-paths astra_camera astra_camera_msgs d_slam jetson_app); fi
