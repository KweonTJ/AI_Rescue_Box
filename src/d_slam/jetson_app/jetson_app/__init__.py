"""AI Rescue Box Jetson application.

Hardware integrations are imported lazily so domain logic and tests work on
machines without ROS 2, Astra, RTAB-Map, CUDA, or a display server.
"""

from .domain import (
    MissionManifest,
    ObservationState,
    OccupancyGrid,
    PersonCandidate,
    Point2D,
    Pose2D,
    RiskZone,
    RoutePlan,
    SemanticResult,
    TeamRecommendation,
)

__all__ = [
    "MissionManifest",
    "ObservationState",
    "OccupancyGrid",
    "PersonCandidate",
    "Point2D",
    "Pose2D",
    "RiskZone",
    "RoutePlan",
    "SemanticResult",
    "TeamRecommendation",
]

__version__ = "0.1.0"
