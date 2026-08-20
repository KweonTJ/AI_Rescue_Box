#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_DIR="$ROOT/data/runtime/jetson"
shopt -s nullglob
pid_files=("$RUNTIME_DIR"/*.pid)
if (( ${#pid_files[@]} == 0 )); then
  echo "Jetson stack is not running (no PID files)."
  exit 0
fi
for file in "${pid_files[@]}"; do
  [[ "$(basename "$file")" == "stack.pid" ]] && continue
  pid="$(cat "$file" 2>/dev/null || true)"
  [[ -z "$pid" ]] && continue
  if kill -0 "$pid" 2>/dev/null; then
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
  fi
done
for _ in {1..20}; do
  alive=false
  for file in "${pid_files[@]}"; do
    [[ "$(basename "$file")" == "stack.pid" ]] && continue
    pid="$(cat "$file" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then alive=true; fi
  done
  [[ "$alive" == false ]] && break
  sleep 0.25
done
for file in "${pid_files[@]}"; do
  [[ "$(basename "$file")" == "stack.pid" ]] && continue
  pid="$(cat "$file" 2>/dev/null || true)"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
  fi
done
rm -f "$RUNTIME_DIR"/*.pid
echo "Jetson stack stopped."
