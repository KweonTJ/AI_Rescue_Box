#!/usr/bin/env bash
UWB_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AI_RESCUE_WS_ROOT="${AI_RESCUE_WS_ROOT:-$(cd "$UWB_ROOT/../.." && pwd)}"
AI_RESCUE_VENV="${AI_RESCUE_VENV:-$AI_RESCUE_WS_ROOT/.venv_uwb}"
AI_RESCUE_ENV_FILE="${AI_RESCUE_ENV_FILE:-$UWB_ROOT/config/jetson.env}"
[[ ! -f "$AI_RESCUE_ENV_FILE" ]] || source "$AI_RESCUE_ENV_FILE"
AI_RESCUE_API_HOST="${AI_RESCUE_API_HOST:-0.0.0.0}"
AI_RESCUE_API_PORT="${AI_RESCUE_API_PORT:-8001}"
AI_RESCUE_PUBLIC_ORIGIN="${AI_RESCUE_PUBLIC_ORIGIN:-https://doubleclick.lab.cbnu.ac.kr}"
AI_RESCUE_JETSON_IP="${AI_RESCUE_JETSON_IP:-192.168.0.11}"
AI_RESCUE_FLUTTER_PORT="${AI_RESCUE_FLUTTER_PORT:-8081}"
AI_RESCUE_LOCAL_ORIGIN="${AI_RESCUE_LOCAL_ORIGIN:-http://${AI_RESCUE_JETSON_IP}:${AI_RESCUE_FLUTTER_PORT}}"
AI_RESCUE_API_BASE_URL="${AI_RESCUE_API_BASE_URL:-http://${AI_RESCUE_JETSON_IP}:${AI_RESCUE_API_PORT}}"
AI_RESCUE_UWB_PORT="${AI_RESCUE_UWB_PORT:-/dev/ttyACM0}"
AI_RESCUE_UWB_BAUDRATE="${AI_RESCUE_UWB_BAUDRATE:-460800}"
AI_RESCUE_UWB_SPOOL="${AI_RESCUE_UWB_SPOOL:-$AI_RESCUE_WS_ROOT/data/uwb_spool}"
ROS_LOCALHOST_ONLY="${ROS_LOCALHOST_ONLY:-1}"
source_safe(){ set +u; source "$1"; set -u; }
activate_runtime(){ [[ -f "$AI_RESCUE_VENV/bin/activate" ]] || { echo "Run $UWB_ROOT/scripts/build.sh first" >&2; return 1; }; source_safe "$AI_RESCUE_VENV/bin/activate"; source_safe /opt/ros/humble/setup.bash; source_safe "$AI_RESCUE_WS_ROOT/install/setup.bash"; export ROS_LOCALHOST_ONLY; }
