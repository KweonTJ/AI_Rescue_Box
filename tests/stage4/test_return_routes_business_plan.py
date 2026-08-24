from __future__ import annotations

from jetson_app.domain import BoundingBox, CameraPoint, OccupancyGrid, PersonCandidate, Point2D
from jetson_app.planning import AStarRoutePlanner
from jetson_app.stage4.return_routes import plan_stage3_return_routes

STAMP = "2026-08-24T00:00:00Z"


def _grid(blocked=()):
    values = [0] * 100
    for x, y in blocked:
        values[y * 10 + x] = 100
    return OccupancyGrid(10, 10, 1.0, Point2D(0.0, 0.0), tuple(values), frame_id="map")


def _victim():
    return PersonCandidate(
        detection_id="victim-1",
        tracking_id=None,
        class_name="person",
        bbox=BoundingBox(0, 0, 10, 20),
        confidence=0.9,
        depth_valid=True,
        camera_position=CameraPoint(0.0, 0.0, 2.0),
        map_position=Point2D(8.5, 1.5),
        detected_at=STAMP,
        source="rgb+depth",
    )


def test_return_route_is_replanned_after_obstacle_not_reversed_entry_route():
    planner = AStarRoutePlanner(occupied_threshold=65, allow_unknown=False, unknown_cost=3.0)
    entrance = Point2D(1.5, 1.5)
    victim = _victim()

    original_grid = _grid()
    entry = planner.plan(
        original_grid,
        entrance,
        victim.map_position,
        (),
        map_version=1,
        target_id=victim.detection_id,
    )

    # The latest map blocks the old straight corridor after the entry route was made.
    latest_grid = _grid(blocked=((4, 1), (5, 1)))
    returns = plan_stage3_return_routes(
        planner,
        latest_grid,
        (victim,),
        (entrance,),
        (),
        (),
        map_version=2,
    )

    assert returns
    route = returns[0]
    assert route["route_id"].startswith("return-victim-1-entrance-")
    assert route["target_id"] == "victim-1"
    assert route["goal_type"] == "entrance"
    assert route["start"] == victim.map_position.to_dict()
    assert route["goal"] == entrance.to_dict()
    assert route["total_distance"] > 0
    assert route["risk_cost"] >= 0
    assert route["rank"] == 1
    assert route["points"] != [point.to_dict() for point in reversed(entry.points)]
