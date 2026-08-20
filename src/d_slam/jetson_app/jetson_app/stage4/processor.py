from __future__ import annotations

from pathlib import Path
from typing import Sequence

from ..alignment import RigidMissionTransform
from ..domain import MissionManifest, RiskZone
from ..providers import SlamSnapshot
from .alignment import ChangeMapBuilder, PriorLiveMapAligner
from .models import PriorMapReference, Stage4Artifacts, Stage4Config
from .traversability import TraversabilityBuilder


class Stage4Processor:
    def __init__(
        self,
        config: Stage4Config | None = None,
        *,
        occupied_threshold: int = 65,
        minimum_passage_width_m: float = 0.8,
    ) -> None:
        self.config = config or Stage4Config()
        self.aligner = PriorLiveMapAligner(self.config, occupied_threshold=occupied_threshold)
        self.change_builder = ChangeMapBuilder(occupied_threshold=occupied_threshold)
        self.traversability_builder = TraversabilityBuilder(
            self.config,
            occupied_threshold=occupied_threshold,
            minimum_passage_width_m=minimum_passage_width_m,
        )

    def prepare(
        self,
        *,
        mission: MissionManifest,
        prior_map_path: Path,
        snapshot: SlamSnapshot,
        initial: RigidMissionTransform,
        risks: Sequence[RiskZone] = (),
    ) -> Stage4Artifacts:
        prior = PriorMapReference.from_image(
            mission,
            prior_map_path,
            dark_threshold=self.config.prior_dark_threshold,
            free_threshold=self.config.prior_free_threshold,
        )
        alignment = self.aligner.align(mission, prior, snapshot, initial)
        change = self.change_builder.build(prior, snapshot, alignment)
        traversability = self.traversability_builder.build(
            prior, snapshot, alignment, change, risks
        )
        return Stage4Artifacts(prior, alignment, change, traversability)
