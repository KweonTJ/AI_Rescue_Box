#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV="${AI_RESCUE_JETSON_VENV:-$ROOT/.venv-jetson}"
COLCON_ROOT="${AI_RESCUE_COLCON_ROOT:-$ROOT/data/jetson_colcon}"
RUNTIME_DIR="$ROOT/data/runtime/jetson"
LOG_DIR="${AI_RESCUE_LOG_DIR:-$ROOT/data/logs/jetson}"

load_env() {
  local file="$1"
  if [[ -f "$file" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$file"
    set +a
  fi
}
load_env "$ROOT/src/d_slam/config/jetson.env"
load_env "$ROOT/src/uwb/config/jetson.env"
LOG_DIR="${AI_RESCUE_LOG_DIR:-$ROOT/data/logs/jetson}"
[[ "$LOG_DIR" = /* ]] || LOG_DIR="$ROOT/$LOG_DIR"
mkdir -p "$RUNTIME_DIR" "$LOG_DIR" "$ROOT/data/jetson" "$ROOT/data/uwb_spool/jetson"

shopt -s nullglob
for pid_file in "$RUNTIME_DIR"/*.pid; do
  [[ "$(basename "$pid_file")" == "stack.pid" ]] && continue
  existing="$(cat "$pid_file" 2>/dev/null || true)"
  if [[ -n "$existing" ]] && kill -0 "$existing" 2>/dev/null; then
    echo "Jetson component is already running: $(basename "$pid_file" .pid) PID=$existing" >&2
    exit 1
  fi
  rm -f "$pid_file"
done
if [[ -f "$RUNTIME_DIR/stack.pid" ]]; then
  existing="$(cat "$RUNTIME_DIR/stack.pid" 2>/dev/null || true)"
  if [[ -n "$existing" ]] && kill -0 "$existing" 2>/dev/null; then
    echo "Jetson launcher is already running (PID $existing)." >&2
    exit 1
  fi
  rm -f "$RUNTIME_DIR/stack.pid"
fi
echo "$$" > "$RUNTIME_DIR/stack.pid"
trap 'rm -f "$RUNTIME_DIR/stack.pid"' EXIT

if [[ -n "${ROS_DISTRO:-}" && -f "/opt/ros/$ROS_DISTRO/setup.bash" ]]; then
  # shellcheck disable=SC1090
  source "/opt/ros/$ROS_DISTRO/setup.bash"
elif [[ -z "${ROS_DISTRO:-}" ]]; then
  echo "ROS_DISTRO is unset. Source ROS2 before start.sh." >&2
  exit 2
fi
if [[ -f "$COLCON_ROOT/install/setup.bash" ]]; then
  # shellcheck disable=SC1090
  source "$COLCON_ROOT/install/setup.bash"
else
  echo "Combined ROS workspace is not built. Run deploy/jetson/install.sh." >&2
  exit 2
fi
if [[ ! -x "$VENV/bin/python" ]]; then
  echo "Jetson virtualenv is missing. Run deploy/jetson/install.sh." >&2
  exit 2
fi
if ! command -v setsid >/dev/null 2>&1; then
  echo "setsid is required (install the util-linux package)." >&2
  exit 2
fi
# shellcheck disable=SC1090
source "$VENV/bin/activate"
VENV_SITE="$($VENV/bin/python -c 'import site; print(site.getsitepackages()[0])')"
export PYTHONPATH="$VENV_SITE:$ROOT/src/uwb:$ROOT/src/uwb/protocol:$ROOT/src/d_slam/jetson_app${PYTHONPATH:+:$PYTHONPATH}"
export ROS_LOCALHOST_ONLY="${ROS_LOCALHOST_ONLY:-1}"

bool_enabled() {
  case "${1:-true}" in 1|true|TRUE|yes|YES|on|ON) return 0 ;; *) return 1 ;; esac
}

start_component() {
  local name="$1"; shift
  local pid_file="$RUNTIME_DIR/$name.pid"
  local log_file="$LOG_DIR/$name.log"
  setsid "$@" >>"$log_file" 2>&1 < /dev/null &
  local pid=$!
  echo "$pid" > "$pid_file"
  sleep 0.8
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "[$name] startup failed; see $log_file" >&2
    tail -n 30 "$log_file" >&2 || true
    "$ROOT/deploy/jetson/stop.sh" >/dev/null 2>&1 || true
    exit 1
  fi
  echo "[$name] RUNNING pid=$pid log=$log_file"
}

DB_PATH="${AI_RESCUE_RTAB_DATABASE:-$ROOT/data/jetson/rtabmap.db}"
[[ "$DB_PATH" = /* ]] || DB_PATH="$ROOT/$DB_PATH"
CONFIG_PATH="${AI_RESCUE_JETSON_CONFIG:-$ROOT/src/d_slam/config/default.yaml}"
[[ "$CONFIG_PATH" = /* ]] || CONFIG_PATH="$ROOT/$CONFIG_PATH"
export AI_RESCUE_JETSON_CONFIG="$CONFIG_PATH"
DATA_ROOT="${AI_RESCUE_DATA_ROOT:-$ROOT/data/jetson}"
[[ "$DATA_ROOT" = /* ]] || DATA_ROOT="$ROOT/$DATA_ROOT"
export AI_RESCUE_DATA_ROOT="$DATA_ROOT"
UWB_SPOOL="${AI_RESCUE_UWB_SPOOL:-$ROOT/data/uwb_spool/jetson}"
[[ "$UWB_SPOOL" = /* ]] || UWB_SPOOL="$ROOT/$UWB_SPOOL"
mkdir -p "$DATA_ROOT" "$UWB_SPOOL" "$(dirname "$DB_PATH")"

if bool_enabled "${AI_RESCUE_START_SLAM:-true}"; then
  start_component slam ros2 launch d_slam d_slam.launch.py \
    database_path:="$DB_PATH" \
    delete_db_on_start:="${AI_RESCUE_DELETE_DB_ON_START:-true}" \
    color_topic:="${AI_RESCUE_RGB_TOPIC:-/camera/color/image_raw}" \
    depth_topic:="${AI_RESCUE_DEPTH_TOPIC:-/camera/depth/image_raw}" \
    camera_info_topic:="${AI_RESCUE_CAMERA_INFO_TOPIC:-/camera/color/camera_info}" \
    map_topic:="${AI_RESCUE_RTAB_MAP_TOPIC:-/rtabmap/map}" \
    odom_topic:="${AI_RESCUE_RTAB_ODOM_TOPIC:-/rtabmap/odom}" \
    map_frame_id:="${AI_RESCUE_SLAM_MAP_FRAME:-map}" \
    odom_frame_id:="${AI_RESCUE_SLAM_ODOM_FRAME:-odom}"
fi
if bool_enabled "${AI_RESCUE_START_MISSION_SERVICE:-true}"; then
  start_component mission "$VENV/bin/python" -m jetson_app.mission.ros_server
fi
if bool_enabled "${AI_RESCUE_START_UWB:-true}"; then
  bridge_args=(
    --port "${AI_RESCUE_UWB_SERIAL_PORT:-${AI_RESCUE_UWB_PORT:-}}"
    --baudrate "${AI_RESCUE_UWB_BAUD:-${AI_RESCUE_UWB_BAUDRATE:-460800}}"
    --spool-dir "$UWB_SPOOL"
    --firmware-ack-timeout "${AI_RESCUE_UWB_FIRMWARE_ACK_TIMEOUT:-2.0}"
    --firmware-max-attempts "${AI_RESCUE_UWB_FIRMWARE_MAX_ATTEMPTS:-3}"
    --stored-ack-timeout "${AI_RESCUE_UWB_STORED_ACK_TIMEOUT:-5.0}"
    --application-ack-timeout "${AI_RESCUE_UWB_APPLICATION_ACK_TIMEOUT:-30.0}"
    --serial-send-timeout "${AI_RESCUE_UWB_SERIAL_SEND_TIMEOUT:-20.0}"
    --send-queue-limit "${AI_RESCUE_UWB_SEND_QUEUE_LIMIT:-32}"
    --reconnect-initial-delay "${AI_RESCUE_UWB_RECONNECT_INITIAL_DELAY:-0.25}"
    --reconnect-max-delay "${AI_RESCUE_UWB_RECONNECT_MAX_DELAY:-3.0}"
    --reconnect-attempts "${AI_RESCUE_UWB_RECONNECT_ATTEMPTS:-6}"
    --reconnect-cooldown "${AI_RESCUE_UWB_RECONNECT_COOLDOWN:-5.0}"
  )
  if bool_enabled "${AI_RESCUE_UWB_AUTO_DISCOVER:-false}"; then bridge_args+=(--auto-discover); fi
  start_component uwb ros2 run uwb_jetson_bridge jetson_bridge "${bridge_args[@]}"
fi
if bool_enabled "${AI_RESCUE_START_STAGE2:-true}"; then
  start_component stage2 "$VENV/bin/python" -m runtime.jetson_stage2_node
fi
if bool_enabled "${AI_RESCUE_START_API:-true}"; then
  start_component api "$VENV/bin/python" -m jetson_app.api
fi

echo "Jetson stack launched. API http://${AI_RESCUE_JETSON_API_HOST:-0.0.0.0}:${AI_RESCUE_JETSON_API_PORT:-8001}"
echo "Missing Astra/UWB hardware remains WAITING or DISCONNECTED; inspect ./deploy/jetson/status.sh."
echo "Logs: $LOG_DIR"
