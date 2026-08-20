#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP="$ROOT/src/d_slam/flutter_app"
MODE=debug
API_URL="${JETSON_API_BASE_URL:-http://192.168.50.1:8001}"
WS_URL="${JETSON_WS_URL:-}"
OUTPUT_DIR="${AI_RESCUE_APK_OUTPUT_DIR:-$ROOT/dist/tablet}"
GENERATED_PATHS=()

cleanup_generated_scaffold() {
  local path
  for path in "${GENERATED_PATHS[@]}"; do
    rm -rf "$path"
  done
}
trap cleanup_generated_scaffold EXIT

bootstrap_android_scaffold() {
  local android="$APP/android"
  local need_scaffold=false
  [[ -f "$android/build.gradle" || -f "$android/build.gradle.kts" ]] || need_scaffold=true
  [[ -f "$android/gradlew" && -f "$android/gradle/wrapper/gradle-wrapper.jar" ]] || need_scaffold=true
  [[ "$need_scaffold" == true ]] || return 0

  local temp_dir bootstrap source target name
  temp_dir="$(mktemp -d)"
  bootstrap="$temp_dir/bootstrap"
  flutter create \
    --platforms=android \
    --org com.airescue \
    --project-name ai_rescue_box_tablet \
    "$bootstrap" >/dev/null

  mkdir -p "$android"
  if [[ ! -f "$android/gradlew" ]]; then
    cp "$bootstrap/android/gradlew" "$android/gradlew"
    chmod +x "$android/gradlew"
    GENERATED_PATHS+=("$android/gradlew")
  fi
  if [[ ! -f "$android/gradlew.bat" ]]; then
    cp "$bootstrap/android/gradlew.bat" "$android/gradlew.bat"
    GENERATED_PATHS+=("$android/gradlew.bat")
  fi
  if [[ ! -d "$android/gradle" ]]; then
    cp -R "$bootstrap/android/gradle" "$android/gradle"
    GENERATED_PATHS+=("$android/gradle")
  fi

  for name in build.gradle build.gradle.kts gradle.properties local.properties; do
    source="$bootstrap/android/$name"
    target="$android/$name"
    if [[ -f "$source" && ! -e "$target" ]]; then
      cp "$source" "$target"
      GENERATED_PATHS+=("$target")
    fi
  done
  if [[ ! -f "$android/settings.gradle" && ! -f "$android/settings.gradle.kts" ]]; then
    for name in settings.gradle settings.gradle.kts; do
      source="$bootstrap/android/$name"
      target="$android/$name"
      if [[ -f "$source" ]]; then
        cp "$source" "$target"
        GENERATED_PATHS+=("$target")
        break
      fi
    done
  fi
  rm -rf "$temp_dir"
}

while (( $# )); do
  case "$1" in
    --debug) MODE=debug; shift ;;
    --release) MODE=release; shift ;;
    --api-url) API_URL="${2:?--api-url requires a value}"; shift 2 ;;
    --ws-url) WS_URL="${2:?--ws-url requires a value}"; shift 2 ;;
    --output-dir) OUTPUT_DIR="${2:?--output-dir requires a value}"; shift 2 ;;
    -h|--help)
      echo "usage: $0 [--debug|--release] [--api-url URL] [--ws-url URL] [--output-dir DIR]"
      exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

command -v flutter >/dev/null 2>&1 || { echo "Flutter SDK is required to build the APK." >&2; exit 1; }
[[ "$API_URL" == http://* || "$API_URL" == https://* ]] || { echo "Jetson API URL must start with http:// or https://" >&2; exit 2; }

if [[ "$MODE" == release ]]; then
  PROPERTIES="$APP/android/key.properties"
  [[ -f "$PROPERTIES" ]] || {
    echo "Release signing is not configured." >&2
    echo "Copy $APP/android/key.properties.example to $PROPERTIES and use a keystore outside the repository." >&2
    exit 2
  }
  for key in storePassword keyPassword keyAlias storeFile; do
    grep -Eq "^${key}=.+" "$PROPERTIES" || { echo "key.properties is missing $key" >&2; exit 2; }
  done
  grep -q 'CHANGE_ME' "$PROPERTIES" && { echo "Replace CHANGE_ME values before release build." >&2; exit 2; }
  store_file="$(sed -n 's/^storeFile=//p' "$PROPERTIES" | tail -n1)"
  [[ -f "$store_file" ]] || { echo "Configured release keystore was not found: $store_file" >&2; exit 2; }
fi

# Stage 1 retained the app source but intentionally trimmed Gradle wrapper/root
# scaffold files. Regenerate only those build-system files from the installed
# Flutter SDK; never overwrite MainActivity, Manifest, Dart source or signing
# configuration.
bootstrap_android_scaffold

cd "$APP"
flutter pub get
args=(build apk "--$MODE" "--dart-define=JETSON_API_BASE_URL=$API_URL")
if [[ -n "$WS_URL" ]]; then args+=("--dart-define=JETSON_WS_URL=$WS_URL"); fi
flutter "${args[@]}"

source_apk="$APP/build/app/outputs/flutter-apk/app-$MODE.apk"
[[ -f "$source_apk" ]] || { echo "APK output was not found: $source_apk" >&2; exit 1; }
mkdir -p "$OUTPUT_DIR"
destination="$OUTPUT_DIR/ai-rescue-box-tablet-$MODE.apk"
cp "$source_apk" "$destination"
sha256sum "$destination" > "$destination.sha256"
echo "Tablet APK ready: $destination"
echo "Jetson API: $API_URL"
echo "This build result does not verify installation, network, or Jetson hardware."
