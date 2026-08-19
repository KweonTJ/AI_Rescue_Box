#!/usr/bin/env python3
"""Fail fast when the app branch drifts from the Stage 0/1 package boundaries."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
EXPECTED_SRC = {"host", "uwb", "d_slam"}
REQUIRED = (
    "src/host",
    "src/uwb",
    "src/d_slam",
    "src/uwb/interfaces/schemas/mission_manifest.schema.json",
    "src/uwb/interfaces/schemas/semantic_result.schema.json",
    "src/uwb/interfaces/schemas/approved_plan.schema.json",
    "src/uwb/interfaces/schemas/map_delta.schema.json",
    "src/uwb/interfaces/schemas/urgent_event.schema.json",
    "src/uwb/interfaces/ros2_ws/src/ai_rescue_interfaces/srv/LoadMission.srv",
    "src/uwb/interfaces/ros2_ws/src/ai_rescue_interfaces/srv/ApplyApprovedPlan.srv",
    "src/uwb/interfaces/ros2_ws/src/ai_rescue_interfaces/srv/MissionControl.srv",
    "src/uwb/interfaces/ros2_ws/src/ai_rescue_interfaces/action/SubmitRescueUpdate.action",
)
FORBIDDEN_PATHS = (
    "common",
    ".stage01_payload",
    ".github/workflows/apply-stage01-temp.yml",
)
LEGACY_TERMS = (
    "prepare_from_rescue_app",
    "RESCUE_APP_ROOT",
    "~/rescue_app",
    "rescue_app/",
    "common/ai_boost",
    "common/contracts",
    "common/flutter_shared",
    "oaiusercontent.com",
)


def main() -> int:
    errors: list[str] = []
    if not SRC.is_dir():
        errors.append("missing src directory")
    else:
        actual = {p.name for p in SRC.iterdir() if p.is_dir()}
        if actual != EXPECTED_SRC:
            errors.append(f"src direct children must be {sorted(EXPECTED_SRC)}, got {sorted(actual)}")

    for relative in REQUIRED:
        if not (ROOT / relative).exists():
            errors.append(f"missing required path: {relative}")
    for relative in FORBIDDEN_PATHS:
        if (ROOT / relative).exists():
            errors.append(f"forbidden path remains: {relative}")

    for schema in (ROOT / "src/uwb/interfaces/schemas").glob("*.json"):
        try:
            value = json.loads(schema.read_text(encoding="utf-8"))
        except Exception as error:
            errors.append(f"invalid JSON schema {schema.relative_to(ROOT)}: {error}")
            continue
        if value.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            errors.append(f"unexpected schema draft: {schema.relative_to(ROOT)}")

    scan_roots = [ROOT / "README.md", ROOT / "docs", ROOT / "scripts", ROOT / "src"]
    for item in scan_roots:
        paths = [item] if item.is_file() else [p for p in item.rglob("*") if p.is_file()]
        for path in paths:
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for term in LEGACY_TERMS:
                if term in text:
                    errors.append(f"legacy term {term!r} remains in {path.relative_to(ROOT)}")

    if errors:
        print("Repository structure check failed:", file=sys.stderr)
        for error in errors:
            print(f" - {error}", file=sys.stderr)
        return 1
    print("Repository structure check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
