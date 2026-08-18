#!/usr/bin/env bash
set -Eeuo pipefail
D="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$D/_runtime_env.sh"
python3 "$UWB_ROOT/scripts/verify_package.py" --root "$UWB_ROOT"
command -v rosdep >/dev/null; command -v colcon >/dev/null
[[ -d "$AI_RESCUE_VENV" ]] || python3 -m venv --system-site-packages "$AI_RESCUE_VENV"
source_safe "$AI_RESCUE_VENV/bin/activate"
python3 -m pip install --upgrade pip setuptools wheel
python3 -m pip install -r "$UWB_ROOT/requirements.txt"
source_safe /opt/ros/humble/setup.bash
rosdep install --from-paths "$UWB_ROOT/jetson_app" "$UWB_ROOT/ros2_ws/src" --ignore-src -r -y
cd "$AI_RESCUE_WS_ROOT"
colcon build --symlink-install --base-paths "$UWB_ROOT/jetson_app" "$UWB_ROOT/ros2_ws/src" --packages-select ai_rescue_uwb_common uwb_interfaces uwb_jetson_bridge jetson_app
printf '[DONE] Jetson FastAPI and UWB workspace built\n'
