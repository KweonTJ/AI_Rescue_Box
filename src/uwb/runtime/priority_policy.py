"""Interface for transmission priority and compression policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol


@dataclass(frozen=True)
class TransmissionDecision:
    priority: int
    send_immediately: bool
    compression_level: int
    preview_max_dimension: int
    reason: str

    def __post_init__(self) -> None:
        if not 0 <= self.priority <= 255:
            raise ValueError("priority must be in [0, 255]")
        if not 0 <= self.compression_level <= 9:
            raise ValueError("compression_level must be in [0, 9]")
        if self.preview_max_dimension < 1:
            raise ValueError("preview_max_dimension must be positive")


class TransmissionPolicy(Protocol):
    def decide(self, features: Mapping[str, float]) -> TransmissionDecision:
        ...
