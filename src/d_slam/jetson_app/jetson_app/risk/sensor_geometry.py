"""Conservative, explainable hazards from map-frame 3-D sensor samples.

This module deliberately has no ROS dependency.  The ROS adapter is
responsible for decoding a Depth image or PointCloud2 and transforming valid
samples into the map frame.  Invalid samples or a missing TF therefore yield
no observations instead of invented geometry.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from statistics import median
from typing import Iterable, Sequence

from ..domain import ObservationState, Point2D, RiskZone, validate_timestamp


@dataclass(frozen=True)
class MapPoint3D:
    """A measured point expressed in the configured SLAM map frame."""

    x: float
    y: float
    z: float

    def __post_init__(self) -> None:
        if not all(math.isfinite(float(value)) for value in (self.x, self.y, self.z)):
            raise ValueError("map point coordinates must be finite")


@dataclass(frozen=True)
class _CellEvidence:
    x: int
    y: int
    samples: tuple[MapPoint3D, ...]
    surface_height: float
    height_spread: float


class ConservativeSensorRiskAnalyzer:
    """Classify only hazards supported by dense, map-frame measurements.

    The rules are intentionally simple and auditable:

    * a dense cell with substantial vertical spread is a debris candidate;
    * two adjacent, independently dense cells with a height discontinuity are
      a step candidate, or a fall candidate above the stricter threshold;
    * no interpolation is performed and no result is emitted from an empty or
      undersampled frame.

    These are candidates, not claims about structural collapse or safety.
    """

    def __init__(
        self,
        *,
        cell_size_m: float = 0.25,
        minimum_points_per_cell: int = 4,
        debris_minimum_points: int = 12,
        debris_height_spread_m: float = 0.30,
        step_height_threshold_m: float = 0.18,
        drop_height_threshold_m: float = 0.45,
        maximum_points: int = 40_000,
    ) -> None:
        if cell_size_m <= 0:
            raise ValueError("sensor risk cell size must be positive")
        if minimum_points_per_cell < 2:
            raise ValueError("minimum sensor samples per cell must be at least two")
        if debris_minimum_points < minimum_points_per_cell:
            raise ValueError("debris point threshold cannot be below the cell threshold")
        if debris_height_spread_m <= 0 or step_height_threshold_m <= 0:
            raise ValueError("sensor risk height thresholds must be positive")
        if drop_height_threshold_m < step_height_threshold_m:
            raise ValueError("drop threshold cannot be below the step threshold")
        if maximum_points < minimum_points_per_cell:
            raise ValueError("maximum sensor points is too small")
        self.cell_size_m = float(cell_size_m)
        self.minimum_points_per_cell = int(minimum_points_per_cell)
        self.debris_minimum_points = int(debris_minimum_points)
        self.debris_height_spread_m = float(debris_height_spread_m)
        self.step_height_threshold_m = float(step_height_threshold_m)
        self.drop_height_threshold_m = float(drop_height_threshold_m)
        self.maximum_points = int(maximum_points)

    def _polygon(self, cells: Sequence[tuple[int, int]]) -> tuple[Point2D, ...]:
        min_x = min(cell[0] for cell in cells) * self.cell_size_m
        max_x = (max(cell[0] for cell in cells) + 1) * self.cell_size_m
        min_y = min(cell[1] for cell in cells) * self.cell_size_m
        max_y = (max(cell[1] for cell in cells) + 1) * self.cell_size_m
        return (
            Point2D(min_x, min_y),
            Point2D(max_x, min_y),
            Point2D(max_x, max_y),
            Point2D(min_x, max_y),
        )

    def _cells(self, points: Iterable[MapPoint3D]) -> dict[tuple[int, int], _CellEvidence]:
        buckets: dict[tuple[int, int], list[MapPoint3D]] = defaultdict(list)
        accepted = 0
        for point in points:
            if accepted >= self.maximum_points:
                break
            if not all(math.isfinite(float(value)) for value in (point.x, point.y, point.z)):
                continue
            key = (
                math.floor(point.x / self.cell_size_m),
                math.floor(point.y / self.cell_size_m),
            )
            buckets[key].append(point)
            accepted += 1
        cells: dict[tuple[int, int], _CellEvidence] = {}
        for (x, y), samples in buckets.items():
            if len(samples) < self.minimum_points_per_cell:
                continue
            heights = sorted(float(point.z) for point in samples)
            # Robust percentiles ignore isolated flying pixels while retaining
            # a genuine vertical distribution in a dense cell.
            low = heights[max(0, int(len(heights) * 0.1) - 1)]
            high = heights[min(len(heights) - 1, int(len(heights) * 0.9))]
            cells[(x, y)] = _CellEvidence(
                x=x,
                y=y,
                samples=tuple(samples),
                surface_height=float(median(heights)),
                height_spread=max(0.0, high - low),
            )
        return cells

    def analyze(
        self,
        points: Iterable[MapPoint3D],
        *,
        source: str,
        observed_at: str,
        map_version: int,
    ) -> tuple[RiskZone, ...]:
        if not source:
            raise ValueError("sensor risk source is required")
        validate_timestamp(observed_at, "sensor risk observed_at")
        if map_version < 1:
            raise ValueError("sensor risk map_version must be positive")
        cells = self._cells(points)
        if not cells:
            return ()

        risks: list[RiskZone] = []
        for key in sorted(cells, key=lambda item: (item[1], item[0])):
            cell = cells[key]
            if (
                len(cell.samples) >= self.debris_minimum_points
                and cell.height_spread >= self.debris_height_spread_m
            ):
                confidence = min(
                    0.95,
                    0.55
                    + 0.02 * (len(cell.samples) - self.debris_minimum_points)
                    + 0.15
                    * min(1.0, cell.height_spread / self.debris_height_spread_m - 1.0),
                )
                risks.append(
                    RiskZone(
                        risk_id=f"sensor-debris-{map_version:04d}-{cell.x}-{cell.y}",
                        risk_type="debris_dense_candidate",
                        polygon=self._polygon((key,)),
                        severity=min(0.9, 0.55 + cell.height_spread / 2.0),
                        confidence=confidence,
                        rationale=(
                            f"{len(cell.samples)} measured points in a "
                            f"{self.cell_size_m:.2f} m cell have robust vertical "
                            f"spread {cell.height_spread:.3f} m"
                        ),
                        source=source,
                        observed_at=observed_at,
                        state=ObservationState.OBSERVED,
                    )
                )

        # Compare each neighboring pair once.  Both cells have already met the
        # independent density threshold, so a single isolated depth pixel can
        # never produce a step/fall candidate.
        for key in sorted(cells, key=lambda item: (item[1], item[0])):
            first = cells[key]
            for neighbor_key in ((key[0] + 1, key[1]), (key[0], key[1] + 1)):
                second = cells.get(neighbor_key)
                if second is None:
                    continue
                difference = abs(first.surface_height - second.surface_height)
                if difference < self.step_height_threshold_m:
                    continue
                fall = difference >= self.drop_height_threshold_m
                risk_type = "fall_hazard_candidate" if fall else "sudden_step_candidate"
                label = "drop/fall edge" if fall else "sudden step"
                confidence = min(
                    0.95,
                    0.55
                    + 0.1 * min(1.0, difference / self.drop_height_threshold_m)
                    + 0.01
                    * min(len(first.samples), len(second.samples)),
                )
                risks.append(
                    RiskZone(
                        risk_id=(
                            f"sensor-{'fall' if fall else 'step'}-{map_version:04d}-"
                            f"{first.x}-{first.y}-{second.x}-{second.y}"
                        ),
                        risk_type=risk_type,
                        polygon=self._polygon((key, neighbor_key)),
                        severity=min(1.0, difference / self.drop_height_threshold_m),
                        confidence=confidence,
                        rationale=(
                            f"adjacent dense measured surfaces differ by "
                            f"{difference:.3f} m; classified only as a {label} candidate"
                        ),
                        source=source,
                        observed_at=observed_at,
                        state=ObservationState.OBSERVED,
                    )
                )
        return tuple(risks)


__all__ = ["ConservativeSensorRiskAnalyzer", "MapPoint3D"]
