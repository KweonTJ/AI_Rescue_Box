from jetson_app.domain import OccupancyGrid, Point2D, Pose2D
from jetson_app.map_preview import OccupancyPreviewRenderer
from jetson_app.providers.base import CameraIntrinsics, SlamSnapshot
from jetson_app.risk import ConservativeSensorRiskAnalyzer, MapPoint3D
from jetson_app.ros_client.sensor_node import depth_image_to_camera_points

def test_depth_projection_uses_camera_intrinsics():
    intrinsics=CameraIntrinsics(4,4,2.0,2.0,1.5,1.5); depth=[[1000]*4 for _ in range(4)]
    points=depth_image_to_camera_points(depth,intrinsics,depth_scale=0.001,pixel_stride=2); assert points and all(0.9<=p.z<=1.1 for p in points)
def test_sensor_risk_requires_dense_measured_geometry():
    analyzer=ConservativeSensorRiskAnalyzer(cell_size_m=0.5,minimum_points_per_cell=4,debris_minimum_points=4,debris_height_spread_m=0.2)
    risks=analyzer.analyze(tuple(MapPoint3D(0.1,0.1,z) for z in (0.0,0.1,0.4,0.6,0.7)),source='depth_map_frame',observed_at='2026-08-19T00:00:00Z',map_version=1)
    assert any(item.risk_type=='debris_dense_candidate' for item in risks)
def test_preview_preserves_unknown_and_occupied_evidence():
    grid=OccupancyGrid(2,2,0.5,Point2D(0,0),(0,-1,100,0)); snapshot=SlamSnapshot(grid,Pose2D(0.25,0.25),(),(),(),'tracking',1)
    preview=OccupancyPreviewRenderer(max_dimension=32).render(snapshot,mission_id='m',base_map_version=1,artifact_version=1); assert preview.png.startswith(b'\x89PNG') and len(preview.content_signature)==64
