from __future__ import annotations
from ..domain import ObservationState, Point2D, RiskZone, utc_now
from ..providers.base import RiskAssessmentProvider, SlamSnapshot

class OccupancyRiskProvider(RiskAssessmentProvider):
    """Expose sensor risks and conservative occupied-cell evidence without inventing safe zones."""
    def __init__(self, occupied_threshold: int = 65) -> None: self.occupied_threshold=occupied_threshold
    def assess(self, snapshot: SlamSnapshot):
        if snapshot.sensor_risks: return snapshot.sensor_risks
        grid=snapshot.occupancy_grid; risks=[]
        for y in range(grid.height):
            for x in range(grid.width):
                if grid.value(x,y) >= self.occupied_threshold:
                    p=grid.cell_to_world((x,y)); half=grid.resolution/2
                    risks.append(RiskZone(f"occ-{x}-{y}","obstacle_candidate",(Point2D(p.x-half,p.y-half),Point2D(p.x+half,p.y-half),Point2D(p.x+half,p.y+half),Point2D(p.x-half,p.y+half)),0.9,0.7,"occupied cell evidence","slam_occupancy",utc_now(),ObservationState.OBSERVED))
        return tuple(risks)
