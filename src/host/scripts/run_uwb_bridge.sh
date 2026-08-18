#!/usr/bin/env bash
set -Eeuo pipefail
D="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$D/_runtime_env.sh"; activate_ros
PORT="${1:-$AI_RESCUE_UWB_PORT}"; if (($#)); then shift; fi
mkdir -p "$AI_RESCUE_UWB_SPOOL"
exec ros2 run uwb_host_bridge host_bridge --ros-args -p port:="$PORT" -p baudrate:="$AI_RESCUE_UWB_BAUDRATE" -p spool_dir:="$AI_RESCUE_UWB_SPOOL" "$@"
