#!/usr/bin/env bash
set -Eeuo pipefail

TARGET_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="${1:-${RESCUE_APP_ROOT:-${HOME}/rescue_app}}"

fail(){ printf '[ERROR] %s\n' "$1" >&2; exit 1; }
need(){ [[ -e "$1" ]] || fail "missing source path: $1"; }
copy_tree(){
  local src="$1" dst="$2"
  need "$src"; mkdir -p "$dst"
  rsync -a --delete \
    --exclude='__pycache__/' --exclude='*.pyc' \
    --exclude='.pytest_cache/' --exclude='.dart_tool/' --exclude='build/' \
    "$src/" "$dst/"
}
copy_file(){ need "$1"; mkdir -p "$(dirname "$2")"; cp -a "$1" "$2"; }
copy_optional(){ [[ ! -f "$1" ]] || copy_file "$1" "$2"; }

command -v rsync >/dev/null || fail 'rsync is required'
command -v python3 >/dev/null || fail 'python3 is required'
SOURCE_ROOT="$(cd "$SOURCE_ROOT" && pwd)"

need "$SOURCE_ROOT/host_app/host_app"
need "$SOURCE_ROOT/host_app/flutter_app/lib"
need "$SOURCE_ROOT/uwb/flutter_shared/lib"
need "$SOURCE_ROOT/uwb/common/ai_rescue_uwb_common"
need "$SOURCE_ROOT/uwb/ros2_ws/src/uwb_host_bridge"

copy_tree "$SOURCE_ROOT/host_app/host_app" "$TARGET_ROOT/host_app/host_app"
for f in pyproject.toml requirements.txt requirements-api.txt; do
  copy_file "$SOURCE_ROOT/host_app/$f" "$TARGET_ROOT/host_app/$f"
done

rm -rf "$TARGET_ROOT/host_app/flutter_app"
mkdir -p "$TARGET_ROOT/host_app/flutter_app"
copy_tree "$SOURCE_ROOT/host_app/flutter_app/lib" "$TARGET_ROOT/host_app/flutter_app/lib"
copy_tree "$SOURCE_ROOT/host_app/flutter_app/web" "$TARGET_ROOT/host_app/flutter_app/web"
for f in pubspec.yaml pubspec.lock analysis_options.yaml .metadata; do
  copy_optional "$SOURCE_ROOT/host_app/flutter_app/$f" "$TARGET_ROOT/host_app/flutter_app/$f"
done

rm -rf "$TARGET_ROOT/flutter_shared"
mkdir -p "$TARGET_ROOT/flutter_shared"
copy_tree "$SOURCE_ROOT/uwb/flutter_shared/lib" "$TARGET_ROOT/flutter_shared/lib"
for f in pubspec.yaml pubspec.lock analysis_options.yaml LICENSE .metadata; do
  copy_optional "$SOURCE_ROOT/uwb/flutter_shared/$f" "$TARGET_ROOT/flutter_shared/$f"
done

python3 - "$TARGET_ROOT/host_app/flutter_app/pubspec.yaml" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); s=p.read_text()
s=s.replace('path: ../../uwb/flutter_shared','path: ../../flutter_shared')
p.write_text(s)
lock=p.with_name('pubspec.lock')
if lock.exists(): lock.write_text(lock.read_text().replace('../../uwb/flutter_shared','../../flutter_shared'))
PY

copy_tree "$SOURCE_ROOT/uwb/common/ai_rescue_uwb_common" "$TARGET_ROOT/common/ai_rescue_uwb_common"
copy_tree "$SOURCE_ROOT/uwb/ros2_ws/src/ai_rescue_uwb_common" "$TARGET_ROOT/ros2_ws/src/ai_rescue_uwb_common"
copy_tree "$SOURCE_ROOT/uwb/ros2_ws/src/uwb_interfaces" "$TARGET_ROOT/ros2_ws/src/uwb_interfaces"
copy_tree "$SOURCE_ROOT/uwb/ros2_ws/src/uwb_host_bridge" "$TARGET_ROOT/ros2_ws/src/uwb_host_bridge"

cat > "$TARGET_ROOT/ros2_ws/src/ai_rescue_uwb_common/CMakeLists.txt" <<'EOF'
cmake_minimum_required(VERSION 3.8)
project(ai_rescue_uwb_common)
find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)
ament_python_install_package(${PROJECT_NAME} PACKAGE_DIR "${CMAKE_CURRENT_LIST_DIR}/../../../common/${PROJECT_NAME}")
ament_package()
EOF

rm -rf "$TARGET_ROOT/host_app/tests" "$TARGET_ROOT/host_app/flutter_app/test" \
  "$TARGET_ROOT/flutter_shared/test" "$TARGET_ROOT/ros2_ws/src/uwb_jetson_bridge" \
  "$TARGET_ROOT/jetson_app" "$TARGET_ROOT/firmware"

chmod +x "$TARGET_ROOT"/scripts/*.sh "$TARGET_ROOT/prepare_from_rescue_app.sh"
python3 "$TARGET_ROOT/scripts/verify_package.py" --root "$TARGET_ROOT"
printf '[DONE] Host Flutter/UWB runtime prepared from %s\n' "$SOURCE_ROOT"
