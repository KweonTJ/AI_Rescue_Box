"""Interface for bounded Prior/Live map alignment assistance."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ai_rescue_contracts import Transform2D


@dataclass(frozen=True)
class AlignmentSuggestion:
    transform: Transform2D
    overlap: float
    wall_match: float
    source: str


class MapAlignmentStrategy(Protocol):
    def align(self, prior_map: Any, live_map: Any, initial: Transform2D) -> AlignmentSuggestion:
        """Return a bounded suggestion; never overwrite observed geometry."""
