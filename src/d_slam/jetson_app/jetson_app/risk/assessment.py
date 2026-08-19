"""Conservative risk rules: sensor evidence stays distinct from unknown space."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from ..domain import ObservationState, Point2D, RiskZone, utc_now
from ..providers.base import RiskAssessmentProvider, SlamSnapshot


@dataclass(frozen=True)
class DepthRiskObservation:
    risk_id: str
    risk_type: str
    polygon: tuple[Point2D, ...]
    severity: float
    confidence: float
    rationale: str
    observed_at: str
    state: ObservationState = ObservationState.OBSERVED


class RuleBasedRiskAssessmentProvider(RiskAssessmentProvider):
    """Create explainable candidates from occupancy and supplied depth evidence."""

    def __init__(
        self,
        *,
        occupied_threshold: int = 65,
        min_component_cells: int = 1,
        include_unknown_regions: bool = True,
        minimum_passage_width_m: float = 0.8,
        disconnected_minimum_cells: int = 4,
    ) -> None:
        if not 0 <= occupied_threshold <= 100:
            raise ValueError("occupied_threshold must be in [0, 100]")
        if min_component_cells < 1:
            raise ValueError("min_component_cells must be positive")
        if minimum_passage_width_m <= 0:
            raise ValueError("minimum passage width must be positive")
        if disconnected_minimum_cells < 1:
            raise ValueError("disconnected component threshold must be positive")
        self.occupied_threshold = occupied_threshold
        self.min_component_cells = min_component_cells
        self.include_unknown_regions = include_unknown_regions
        self.minimum_passage_width_m = minimum_passage_width_m
        self.disconnected_minimum_cells = disconnected_minimum_cells
        self._depth_observations: tuple[DepthRiskObservation, ...] = ()

    def set_depth_observations(
        self, observations: Iterable[DepthRiskObservation]
    ) -> None:
        self._depth_observations = tuple(observations)

    @staticmethod
    def _components(
        snapshot: SlamSnapshot, predicate: Callable[[int], bool]
    ) -> list[list[tuple[int, int]]]:
        grid = snapshot.occupancy_grid
        remaining = {
            (x, y)
            for y in range(grid.height)
            for x in range(grid.width)
            if predicate(grid.value(x, y))
        }
        components: list[list[tuple[int, int]]] = []
        while remaining:
            start = min(remaining, key=lambda item: (item[1], item[0]))
            remaining.remove(start)
            queue = deque([start])
            component = []
            while queue:
                cell = queue.popleft()
                component.append(cell)
                x, y = cell
                for neighbor in ((x, y - 1), (x - 1, y), (x + 1, y), (x, y + 1)):
                    if neighbor in remaining:
                        remaining.remove(neighbor)
                        queue.append(neighbor)
            components.append(component)
        return components

    @staticmethod
    def _component_polygon(snapshot: SlamSnapshot, cells: Sequence[tuple[int, int]]) -> tuple[Point2D, ...]:
        grid = snapshot.occupancy_grid
        min_x = min(cell[0] for cell in cells)
        max_x = max(cell[0] for cell in cells) + 1
        min_y = min(cell[1] for cell in cells)
        max_y = max(cell[1] for cell in cells) + 1
        ox, oy, resolution = grid.origin.x, grid.origin.y, grid.resolution
        return (
            Point2D(ox + min_x * resolution, oy + min_y * resolution),
            Point2D(ox + max_x * resolution, oy + min_y * resolution),
            Point2D(ox + max_x * resolution, oy + max_y * resolution),
            Point2D(ox + min_x * resolution, oy + max_y * resolution),
        )

    def _narrow_passage_cells(self, snapshot: SlamSnapshot) -> set[tuple[int, int]]:
        """Return known-free cells bounded by measured occupancy on both sides."""

        grid = snapshot.occupancy_grid
        maximum_cells = max(1, math.ceil(self.minimum_passage_width_m / grid.resolution))

        def occupied_distance(x: int, y: int, dx: int, dy: int) -> int | None:
            for distance in range(1, maximum_cells + 1):
                nx, ny = x + dx * distance, y + dy * distance
                if not (0 <= nx < grid.width and 0 <= ny < grid.height):
                    return None
                value = grid.value(nx, ny)
                if value == -1:
                    return None
                if value >= self.occupied_threshold:
                    return distance
            return None

        narrow: set[tuple[int, int]] = set()
        for y in range(grid.height):
            for x in range(grid.width):
                value = grid.value(x, y)
                if value < 0 or value >= self.occupied_threshold:
                    continue
                for first, second in (((-1, 0), (1, 0)), ((0, -1), (0, 1))):
                    left = occupied_distance(x, y, *first)
                    right = occupied_distance(x, y, *second)
                    if left is None or right is None:
                        continue
                    measured_width = (left + right - 1) * grid.resolution
                    if measured_width < self.minimum_passage_width_m:
                        narrow.add((x, y))
                        break
        return narrow

    def _disconnected_free_components(
        self, snapshot: SlamSnapshot
    ) -> list[list[tuple[int, int]]]:
        """Known traversable islands separated from the robot's component."""

        grid = snapshot.occupancy_grid
        components = self._components(
            snapshot, lambda value: 0 <= value < self.occupied_threshold
        )
        try:
            robot_cell = grid.world_to_cell(snapshot.robot_pose)
        except IndexError:
            return []
        robot_component = next(
            (component for component in components if robot_cell in component), None
        )
        if robot_component is None:
            return []
        return [
            component
            for component in components
            if component is not robot_component
            and len(component) >= self.disconnected_minimum_cells
        ]

    def assess(self, snapshot: SlamSnapshot) -> Sequence[RiskZone]:
        now = snapshot.timestamp
        risks: list[RiskZone] = []
        occupied = self._components(
            snapshot, lambda value: value >= self.occupied_threshold
        )
        for index, cells in enumerate(occupied, 1):
            if len(cells) < self.min_component_cells:
                continue
            confidence = min(0.99, 0.65 + 0.02 * len(cells))
            risks.append(
                RiskZone(
                    risk_id=f"obstacle-{snapshot.map_version:04d}-{index:04d}",
                    risk_type="obstacle_candidate",
                    polygon=self._component_polygon(snapshot, cells),
                    severity=min(1.0, 0.7 + 0.01 * len(cells)),
                    confidence=confidence,
                    rationale=f"{len(cells)} occupied grid cell(s) at or above {self.occupied_threshold}",
                    source="occupancy_grid",
                    observed_at=now,
                    state=ObservationState.OBSERVED,
                )
            )
        if self.include_unknown_regions:
            unknown = self._components(snapshot, lambda value: value == -1)
            for index, cells in enumerate(unknown, 1):
                risks.append(
                    RiskZone(
                        risk_id=f"unknown-{snapshot.map_version:04d}-{index:04d}",
                        risk_type="unknown_area",
                        polygon=self._component_polygon(snapshot, cells),
                        severity=1.0,
                        confidence=1.0,
                        rationale="occupancy grid has no observation for this connected region",
                        source="occupancy_grid",
                        observed_at=now,
                        state=ObservationState.UNKNOWN,
                    )
                )
        if snapshot.tracking_status.lower() not in {
            "tracking",
            "ok",
            "mock_tracking",
        }:
            point = snapshot.robot_pose
            radius = snapshot.occupancy_grid.resolution
            risks.append(
                RiskZone(
                    risk_id=f"slam-unstable-{snapshot.map_version:04d}",
                    risk_type="low_sensor_confidence",
                    polygon=(
                        Point2D(point.x - radius, point.y - radius),
                        Point2D(point.x + radius, point.y - radius),
                        Point2D(point.x + radius, point.y + radius),
                        Point2D(point.x - radius, point.y + radius),
                    ),
                    severity=0.6,
                    confidence=0.8,
                    rationale=f"SLAM tracking state is {snapshot.tracking_status!r}",
                    source="rtabmap_status",
                    observed_at=now,
                    state=ObservationState.OBSERVED,
                )
            )
        narrow_cells = self._narrow_passage_cells(snapshot)
        if narrow_cells:
            # `_components` operates on cell values, which cannot distinguish
            # equal-valued cells. Build the few narrow components explicitly.
            remaining = set(narrow_cells)
            narrow_components = []
            while remaining:
                first = min(remaining, key=lambda item: (item[1], item[0]))
                remaining.remove(first)
                queue, component = deque([first]), []
                while queue:
                    cell = queue.popleft()
                    component.append(cell)
                    x, y = cell
                    for neighbor in (
                        (x - 1, y),
                        (x + 1, y),
                        (x, y - 1),
                        (x, y + 1),
                    ):
                        if neighbor in remaining:
                            remaining.remove(neighbor)
                            queue.append(neighbor)
                narrow_components.append(component)
            for index, cells in enumerate(narrow_components, 1):
                risks.append(
                    RiskZone(
                        risk_id=f"narrow-{snapshot.map_version:04d}-{index:04d}",
                        risk_type="insufficient_passage_width_candidate",
                        polygon=self._component_polygon(snapshot, cells),
                        severity=0.75,
                        confidence=0.75,
                        rationale=(
                            "known-free occupancy cells are bounded by observed "
                            f"obstacles at less than {self.minimum_passage_width_m:.2f} m"
                        ),
                        source="occupancy_grid_clearance",
                        observed_at=now,
                        state=ObservationState.OBSERVED,
                    )
                )
        for index, cells in enumerate(
            self._disconnected_free_components(snapshot), 1
        ):
            risks.append(
                RiskZone(
                    risk_id=f"disconnected-{snapshot.map_version:04d}-{index:04d}",
                    risk_type="path_disconnection_candidate",
                    polygon=self._component_polygon(snapshot, cells),
                    severity=0.8,
                    confidence=0.7,
                    rationale=(
                        f"{len(cells)} known traversable cells form a component "
                        "not connected to the robot's known-free component"
                    ),
                    source="occupancy_grid_connectivity",
                    observed_at=now,
                    state=ObservationState.OBSERVED,
                )
            )
        for observation in self._depth_observations:
            risks.append(
                RiskZone(
                    risk_id=observation.risk_id,
                    risk_type=observation.risk_type,
                    polygon=observation.polygon,
                    severity=observation.severity,
                    confidence=observation.confidence,
                    rationale=observation.rationale,
                    source="depth_or_pointcloud",
                    observed_at=observation.observed_at,
                    state=observation.state,
                )
            )
        # Real Depth/PointCloud evidence is decoded and transformed by the ROS
        # adapter before it enters the dependency-free snapshot.  Never infer a
        # sensor hazard merely because the tuple is empty.
        risks.extend(snapshot.sensor_risks)
        return tuple(risks)

    @staticmethod
    def interpolated_gap(
        *,
        risk_id: str,
        risk_type: str,
        polygon: Sequence[Point2D],
        gap_m: float,
        maximum_gap_m: float,
        rationale: str,
    ) -> DepthRiskObservation:
        """Explicitly mark only a bounded short sensor gap as interpolated."""

        if gap_m < 0 or maximum_gap_m <= 0 or gap_m > maximum_gap_m:
            raise ValueError("sensor gap is too large to interpolate")
        return DepthRiskObservation(
            risk_id=risk_id,
            risk_type=risk_type,
            polygon=tuple(polygon),
            severity=0.7,
            confidence=max(0.1, 1.0 - gap_m / maximum_gap_m),
            rationale=rationale,
            observed_at=utc_now(),
            state=ObservationState.INTERPOLATED,
        )
