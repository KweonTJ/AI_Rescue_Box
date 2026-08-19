from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol
from ..domain import CameraPoint, Point2D
from ..providers.base import DepthProvider, MapTransformer, PersonDetectionProvider, SlamProvider

class TfPort(MapTransformer, Protocol):
    pass

@dataclass(frozen=True)
class SensorPorts:
    slam: SlamProvider
    detector: PersonDetectionProvider | None = None
    depth: DepthProvider | None = None
    tf: MapTransformer | None = None
