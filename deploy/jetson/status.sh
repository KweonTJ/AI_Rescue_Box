#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_DIR="$ROOT/data/runtime/jetson"
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

process_state() {
  local name="$1" file="$RUNTIME_DIR/$1.pid"
  if [[ -f "$file" ]]; then
    local pid; pid="$(cat "$file" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then printf 'RUNNING (PID %s)' "$pid"; return; fi
  fi
  printf 'STOPPED'
}

topic_exists() {
  command -v ros2 >/dev/null 2>&1 && timeout 3 ros2 topic list 2>/dev/null | grep -Fxq "$1"
}

LOG_DIR="${AI_RESCUE_LOG_DIR:-$ROOT/data/logs/jetson}"
[[ "$LOG_DIR" = /* ]] || LOG_DIR="$ROOT/$LOG_DIR"
API_HOST="${AI_RESCUE_JETSON_API_HOST:-127.0.0.1}"
[[ "$API_HOST" == "0.0.0.0" ]] && API_HOST=127.0.0.1
API_PORT="${AI_RESCUE_JETSON_API_PORT:-8001}"
API_STATE=STOPPED
if [[ "$(process_state api)" == RUNNING* ]]; then
  if command -v curl >/dev/null 2>&1 && curl -fsS --max-time 3 "http://$API_HOST:$API_PORT/api/v1/health" >/dev/null 2>&1; then API_STATE=READY; else API_STATE=STARTING/UNREACHABLE; fi
fi
ASTRA_STATE=WAITING
(topic_exists "${AI_RESCUE_RGB_TOPIC:-/camera/color/image_raw}" && topic_exists "${AI_RESCUE_DEPTH_TOPIC:-/camera/depth/image_raw}") && ASTRA_STATE=READY
RTAB_STATE=WAITING
topic_exists "${AI_RESCUE_RTAB_MAP_TOPIC:-/rtabmap/map}" && RTAB_STATE=READY
MODEL_STATE=NOT_CONFIGURED
MODEL_PATH="${AI_RESCUE_YOLO_MODEL:-}"
if [[ -n "$MODEL_PATH" ]]; then
  [[ "$MODEL_PATH" = /* ]] || MODEL_PATH="$ROOT/$MODEL_PATH"
  [[ -f "$MODEL_PATH" ]] && MODEL_STATE=CONFIGURED || MODEL_STATE=MISSING
fi
UWB_STATE=DISCONNECTED
if command -v ros2 >/dev/null 2>&1 && [[ "$(process_state uwb)" == RUNNING* ]]; then
  status_text="$(timeout 3 ros2 topic echo --once /uwb/status 2>/dev/null || true)"
  if grep -q 'serial_connected: true' <<<"$status_text"; then UWB_STATE=CONNECTED
  elif grep -q 'serial_connected: false' <<<"$status_text"; then UWB_STATE=DISCONNECTED
  else UWB_STATE=WAITING; fi
fi

printf '%-18s %s\n' "SLAM process" "$(process_state slam)"
printf '%-18s %s\n' "Mission service" "$(process_state mission)"
printf '%-18s %s\n' "Jetson UWB" "$(process_state uwb) / $UWB_STATE"
printf '%-18s %s\n' "Stage 2 runtime" "$(process_state stage2)"
printf '%-18s %s\n' "Jetson API" "$(process_state api) / $API_STATE"
printf '%-18s %s\n' "Astra topics" "$ASTRA_STATE"
printf '%-18s %s\n' "RTAB-Map topic" "$RTAB_STATE"
printf '%-18s %s\n' "YOLO model" "$MODEL_STATE"
printf '%-18s %s\n' "Logs" "$LOG_DIR"
