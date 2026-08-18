"""Host reconstruction strategy contract."""

from __future__ import annotations

from typing import Any, Protocol


class ReconstructionStrategy(Protocol):
    def reconstruct(self, previous: Any, delta: Any, semantic_result: Any) -> Any:
        """Preserve observed/prior/interpolated provenance in the returned map."""
