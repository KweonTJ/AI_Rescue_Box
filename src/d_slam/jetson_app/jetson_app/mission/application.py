"""Stage 2 application boundary used by UWB adapters and ROS services."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..domain import MissionManifest
from .manager import MissionManager


@dataclass(frozen=True)
class MissionApplicationResult:
    success: bool
    state: str
    error_code: str = ""
    message: str = ""


class MissionApplicationService:
    def __init__(self, manager: MissionManager) -> None:
        self.manager = manager

    @staticmethod
    def _read(path: Path) -> Mapping[str, Any]:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(value, Mapping):
            raise ValueError("artifact JSON root must be an object")
        return value

    def load_mission(
        self,
        *,
        mission_id: str,
        mission_version: int,
        base_map_path: Path,
        mission_manifest_path: Path,
    ) -> MissionApplicationResult:
        try:
            manifest = MissionManifest.from_dict(self._read(mission_manifest_path))
            if manifest.mission_id != mission_id:
                raise ValueError("LoadMission mission_id does not match manifest")
            if manifest.mission_version != int(mission_version):
                raise ValueError("LoadMission mission_version does not match manifest")
            self.manager.apply_mission(mission_manifest_path, base_map_path)
        except Exception as error:
            return MissionApplicationResult(
                False, "REJECTED", type(error).__name__.upper(), str(error)
            )
        return MissionApplicationResult(True, "READY", "", "mission verified and active")

    def apply_approved_plan(
        self,
        *,
        mission_id: str,
        mission_version: int,
        approved_plan_version: int,
        approved_plan_path: Path,
    ) -> MissionApplicationResult:
        try:
            value = self._read(approved_plan_path)
            if str(value.get("mission_id", "")) != mission_id:
                raise ValueError("ApplyApprovedPlan mission_id does not match artifact")
            if int(value.get("mission_version", 0)) != int(mission_version):
                raise ValueError("ApplyApprovedPlan mission_version does not match artifact")
            if int(value.get("approved_plan_version", 0)) != int(approved_plan_version):
                raise ValueError("ApplyApprovedPlan approved_plan_version does not match artifact")
            self.manager.apply_approved_plan(
                mission_id,
                int(mission_version),
                Path(approved_plan_path),
            )
        except Exception as error:
            return MissionApplicationResult(
                False, "REJECTED", type(error).__name__.upper(), str(error)
            )
        return MissionApplicationResult(True, "APPLIED", "", "approved plan stored")


__all__ = ["MissionApplicationResult", "MissionApplicationService"]
