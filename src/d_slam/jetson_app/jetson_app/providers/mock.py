from __future__ import annotations
from typing import Sequence
from ..domain import OccupancyGrid, Point2D, Pose2D, RiskZone, TeamRecommendation
from .base import ProviderMode, ProviderStatus, RiskAssessmentProvider, SlamProvider, SlamSnapshot, TeamRecommendationProvider

class MockSlamProvider(SlamProvider):
    def __init__(self, snapshot: SlamSnapshot | None = None) -> None:
        self._snapshot = snapshot or SlamSnapshot(OccupancyGrid(4,4,1.0,Point2D(0,0),(0,)*16), Pose2D(.5,.5,0), (Pose2D(.5,.5,0),), (), (), "tracking", 1)
    def status(self) -> ProviderStatus: return ProviderStatus("SLAM", ProviderMode.MOCK, True, "deterministic mock")
    def snapshot(self) -> SlamSnapshot: return self._snapshot

class MockRiskProvider(RiskAssessmentProvider):
    def __init__(self, risks: Sequence[RiskZone] = ()) -> None: self.risks=tuple(risks)
    def assess(self, snapshot: SlamSnapshot): return self.risks or snapshot.sensor_risks

class MockTeamProvider(TeamRecommendationProvider):
    def recommend(self, *, team_count, rescuer_count, candidates, routes, waiting_points, priorities=None):
        del rescuer_count, candidates, priorities
        result=[]
        for index in range(team_count):
            route = routes[index] if index < len(routes) else None
            if route is None and not waiting_points: break
            position = route.start if route else waiting_points[min(index, len(waiting_points)-1)]
            result.append(TeamRecommendation(f"team-{index+1:02d}", position, route.target_id if route else None, route.route_id if route else None, route.total_distance if route else 0.0, route.risk_cost if route else 0.0, "deterministic mock recommendation", 0.7))
        return tuple(result)
