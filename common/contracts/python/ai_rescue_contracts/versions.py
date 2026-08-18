"""Independent monotonic version vector."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VersionVector:
    mission_version: int
    slam_map_version: int = 0
    result_version: int = 0
    approved_plan_version: int = 0

    def __post_init__(self) -> None:
        for name, value in vars(self).items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.mission_version < 1:
            raise ValueError("mission_version must be positive")

    def accepts(self, newer: "VersionVector") -> bool:
        if newer.mission_version < self.mission_version:
            return False
        if newer.mission_version > self.mission_version:
            return True
        return (
            newer.slam_map_version >= self.slam_map_version
            and newer.result_version >= self.result_version
            and newer.approved_plan_version >= self.approved_plan_version
        )
