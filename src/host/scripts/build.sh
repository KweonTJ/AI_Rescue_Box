#!/usr/bin/env bash
set -Eeuo pipefail
D="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$D/_runtime_env.sh"
python3 "$HOST_ROOT/scripts/verify_package.py" --root "$HOST_ROOT"
command -v rosdep >/dev/null; command -v colcon >/dev/null
[[ -d "$AI_RESCUE_VENV" ]] || python3 -m venv --system-site-packages "$AI_RESCUE_VENV"
source_safe "$AI_RESCUE_VENV/bin/activate"
python3 -m pip install --upgrade pip setuptools wheel
python3 -m pip install -r "$HOST_ROOT/requirements.txt"
python3 -m pip install -e "$HOST_ROOT/host_app"
source_safe /opt/ros/humble/setup.bash
rosdep install --from-paths "$HOST_ROOT/ros2_ws/src" --ignore-src -r -y
cd "$AI_RESCUE_WS_ROOT"
colcon build --symlink-install --base-paths "$HOST_ROOT/ros2_ws/src" --packages-select ai_rescue_uwb_common uwb_interfaces uwb_host_bridge
printf '[DONE] Host FastAPI and UWB workspace built\n'
