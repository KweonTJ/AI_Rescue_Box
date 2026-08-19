from jetson_app.domain import OccupancyGrid, Point2D
from jetson_app.planning import AStarRoutePlanner

def test_astar_routes_across_free_grid():
    grid=OccupancyGrid(4,4,1.0,Point2D(0,0),(0,)*16)
    route=AStarRoutePlanner().plan(grid,Point2D(.5,.5),Point2D(3.5,3.5),(),map_version=1)
    assert route.points[0]==Point2D(.5,.5) and route.points[-1]==Point2D(3.5,3.5)
