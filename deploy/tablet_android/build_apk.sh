#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP_ROOT="$ROOT/src/d_slam/flutter_app"
JETSON_API_BASE_URL="${JETSON_API_BASE_URL:-http://192.168.50.1:8001}"

command -v flutter >/dev/null 2>&1 || {
  echo "flutter was not found in PATH" >&2
  exit 1
}

bootstrap_android_wrapper() {
  local wrapper_jar="$APP_ROOT/android/gradle/wrapper/gradle-wrapper.jar"
  local gradlew="$APP_ROOT/android/gradlew"
  if [[ -f "$wrapper_jar" && -f "$gradlew" ]]; then
    return
  fi

  # Stage 1 source already contains the Android app/manifest.  The trimmed
  # project did not retain Gradle wrapper binaries, so generate only the
  # Flutter-SDK-compatible wrapper/build scaffold in a temporary project.
  local temp_dir
  temp_dir="$(mktemp -d)"
  trap 'rm -rf "$temp_dir"' RETURN
  flutter create \
    --platforms=android \
    --org com.airescue \
    --project-name ai_rescue_box_tablet \
    "$temp_dir/bootstrap" >/dev/null

  mkdir -p "$APP_ROOT/android"
  cp "$temp_dir/bootstrap/android/gradlew" "$APP_ROOT/android/gradlew"
  cp "$temp_dir/bootstrap/android/gradlew.bat" "$APP_ROOT/android/gradlew.bat"
  rm -rf "$APP_ROOT/android/gradle"
  cp -R "$temp_dir/bootstrap/android/gradle" "$APP_ROOT/android/gradle"

  for name in build.gradle build.gradle.kts gradle.properties settings.gradle settings.gradle.kts local.properties; do
    if [[ -f "$temp_dir/bootstrap/android/$name" ]]; then
      cp "$temp_dir/bootstrap/android/$name" "$APP_ROOT/android/$name"
    fi
  done
  chmod +x "$APP_ROOT/android/gradlew"
}

bootstrap_android_wrapper

cd "$APP_ROOT"
flutter pub get
flutter build apk --debug \
  --dart-define="JETSON_API_BASE_URL=$JETSON_API_BASE_URL"

APK="$APP_ROOT/build/app/outputs/flutter-apk/app-debug.apk"
[[ -f "$APK" ]] || {
  echo "debug APK was not produced: $APK" >&2
  exit 1
}
printf 'Tablet debug APK: %s\n' "$APK"
printf 'Jetson API: %s\n' "$JETSON_API_BASE_URL"
