#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV="${AI_RESCUE_JETSON_VENV:-$ROOT/.venv-jetson}"
COLCON_ROOT="${AI_RESCUE_COLCON_ROOT:-$ROOT/data/jetson_colcon}"
CHECK_ONLY=false
SKIP_ROS_BUILD=false
for argument in "$@"; do
  case "$argument" in
    --check-only) CHECK_ONLY=true ;;
    --skip-ros-build) SKIP_ROS_BUILD=true ;;
    *) echo "unknown argument: $argument" >&2; exit 2 ;;
  esac
done

info() { printf '[INFO] %s\n' "$*"; }
warn() { printf '[WAITING] %s\n' "$*" >&2; }
require_command() {
  if command -v "$1" >/dev/null 2>&1; then info "$1: FOUND"; return 0; fi
  warn "$1: MISSING"; return 1
}

cd "$ROOT"
require_command python3 || exit 1
require_command setsid || warn "setsid is required by deploy/jetson/start.sh (usually provided by util-linux)"
require_command timeout || warn "timeout is required by deploy/jetson/status.sh (usually provided by coreutils)"
python3 - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("Python 3.10+ is required")
print(f"[INFO] Python: {sys.version.split()[0]}")
PY

mkdir -p \
  "$ROOT/data/jetson" \
  "$ROOT/data/logs/jetson" \
  "$ROOT/data/runtime/jetson" \
  "$ROOT/data/uwb_spool/jetson" \
  "$COLCON_ROOT/build" "$COLCON_ROOT/install" "$COLCON_ROOT/log"

if [[ "$CHECK_ONLY" != true ]]; then
  if [[ ! -x "$VENV/bin/python" ]]; then
    python3 -m venv --system-site-packages "$VENV"
  fi
  "$VENV/bin/python" -m pip install --upgrade pip
  "$VENV/bin/python" -m pip install \
    -e "$ROOT/src/uwb/protocol[serial]" \
    -e "$ROOT/src/d_slam/jetson_app[api]"
  info "Jetson Python environment: $VENV"
else
  [[ -x "$VENV/bin/python" ]] && info "Jetson virtualenv: READY" || warn "Jetson virtualenv: MISSING (run install.sh)"
fi

for module in yaml PIL fastapi uvicorn serial numpy cv2; do
  if [[ -x "$VENV/bin/python" ]] && "$VENV/bin/python" -c "import $module" >/dev/null 2>&1; then
    info "Python module $module: FOUND"
  else
    warn "Python module $module: MISSING"
  fi
done

ROS_READY=true
require_command ros2 || ROS_READY=false
require_command colcon || ROS_READY=false
if [[ -z "${ROS_DISTRO:-}" ]]; then
  warn "ROS_DISTRO is unset; source /opt/ros/<distro>/setup.bash"
  ROS_READY=false
else
  info "ROS_DISTRO=$ROS_DISTRO"
fi
if command -v ros2 >/dev/null 2>&1; then
  ros2 pkg prefix rtabmap_slam >/dev/null 2>&1 && info "RTAB-Map ROS package: FOUND" || warn "RTAB-Map ROS package: MISSING"
fi

if [[ "$CHECK_ONLY" != true && "$SKIP_ROS_BUILD" != true && "$ROS_READY" == true ]]; then
  info "Building existing Astra/d_slam/UWB/interface packages into $COLCON_ROOT/install"
  colcon build --symlink-install \
    --build-base "$COLCON_ROOT/build" \
    --install-base "$COLCON_ROOT/install" \
    --log-base "$COLCON_ROOT/log" \
    --base-paths \
      "$ROOT/src/d_slam/astra_camera" \
      "$ROOT/src/d_slam/astra_camera_msgs" \
      "$ROOT/src/d_slam/d_slam" \
      "$ROOT/src/d_slam/jetson_app" \
      "$ROOT/src/uwb/interfaces/ros2/ai_rescue_interfaces" \
      "$ROOT/src/uwb/ros2_ws/src/uwb_interfaces" \
      "$ROOT/src/uwb/ros2_ws/src/uwb_jetson_bridge"
  info "ROS workspace build: COMPLETE (hardware not started)"
elif [[ "$SKIP_ROS_BUILD" == true ]]; then
  info "ROS workspace build: SKIPPED by argument"
elif [[ "$ROS_READY" != true ]]; then
  warn "ROS workspace build: WAITING for sourced ROS2/colcon"
fi

for pair in \
  "$ROOT/src/d_slam/config/jetson.env.example:$ROOT/src/d_slam/config/jetson.env" \
  "$ROOT/src/uwb/config/jetson.env.example:$ROOT/src/uwb/config/jetson.env"; do
  example="${pair%%:*}"; target="${pair#*:}"
  if [[ ! -f "$target" ]]; then
    warn "machine config absent: cp '$example' '$target'"
  fi
done

MODEL="${AI_RESCUE_YOLO_MODEL:-}"
if [[ -n "$MODEL" && -f "$MODEL" ]]; then
  info "YOLO model: CONFIGURED ($MODEL)"
else
  warn "YOLO model: NOT CONFIGURED; set AI_RESCUE_YOLO_MODEL before real inference"
fi

info "No Astra, RTAB-Map live stream, ESP32, hotspot, udev or systemd action was executed."
info "Next: edit env files, then ./deploy/jetson/start.sh"
