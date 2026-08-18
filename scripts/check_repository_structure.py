#!/usr/bin/env python3
"""Fail fast when the app branch drifts from the agreed package boundaries."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "src/host",
    "src/uwb",
    "src/d_slam",
    "common/contracts/schemas/mission_manifest.schema.json",
    "common/contracts/schemas/semantic_result.schema.json",
    "common/contracts/ros2_ws/src/ai_rescue_interfaces/srv/LoadMission.srv",
    "common/ai_boost/d_slam/alignment.py",
)
FORBIDDEN_ROOTS = ("host", "uwb", "d_slam")


def main() -> int:
    errors: list[str] = []
    for relative in REQUIRED:
        if not (ROOT / relative).exists():
            errors.append(f"missing required path: {relative}")
    for relative in FORBIDDEN_ROOTS:
        if (ROOT / relative).exists():
            errors.append(f"legacy root package still exists: {relative}")
    for prepare in ROOT.glob("src/*/prepare_from_rescue_app.sh"):
        errors.append(f"external source preparation script remains: {prepare.relative_to(ROOT)}")
    for schema in (ROOT / "common/contracts/schemas").glob("*.json"):
        try:
            value = json.loads(schema.read_text(encoding="utf-8"))
        except Exception as error:
            errors.append(f"invalid JSON schema {schema.relative_to(ROOT)}: {error}")
            continue
        if value.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            errors.append(f"unexpected schema draft: {schema.relative_to(ROOT)}")
    if errors:
        print("Repository structure check failed:", file=sys.stderr)
        for error in errors:
            print(f" - {error}", file=sys.stderr)
        return 1
    print("Repository structure check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
