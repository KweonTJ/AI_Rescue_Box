import pytest
from jetson_app.domain import MissionManifest, SemanticResult, Pose2D, ValidationError
from jetson_app.mission.artifacts import validate_semantic_result

def manifest(): return {'schema_version':'1.0','mission_id':'m1','mission_version':1,'artifact_version':1,'mission_name':'test','created_at':'2026-08-19T00:00:00Z','base_map_filename':'map.png','base_map_sha256':'0'*64,'base_map_width':10,'base_map_height':10,'meters_per_pixel':0.1,'robot_start':{'x':0,'y':0,'yaw':0},'entrances':[{'x':0,'y':0}],'available_teams':1,'available_rescuers':2,'coordinate_frame':'mission_map','units':'meters','source':'host','confidence':1.0}
def semantic(): return {'schema_version':'1.0','mission_id':'m1','base_map_version':1,'slam_map_version':1,'result_version':1,'artifact_version':1,'created_at':'2026-08-19T00:00:00Z','coordinate_frame':'mission_map','units':'meters','source':'jetson_sensor_analysis','confidence':0.8,'robot_pose':{'x':0,'y':0,'yaw':0},'robot_trajectory':[],'victim_candidates':[],'confirmed_victims':[],'obstacles':[],'risk_zones':[],'entry_routes':[],'team_recommendations':[],'safe_waiting_points':[],'explored_areas':[],'unknown_areas':[]}
def test_manifest_frame_contract(): assert MissionManifest.from_dict(manifest()).coordinate_frame=='mission_map'
def test_manifest_bad_frame():
    value=manifest(); value['coordinate_frame']='map'
    with pytest.raises(ValidationError): MissionManifest.from_dict(value)
def test_semantic_validator_matches_required_arrays(): assert validate_semantic_result(semantic())['team_recommendations']==[]
def test_semantic_missing_team_recommendations():
    value=semantic(); value.pop('team_recommendations')
    with pytest.raises(ValidationError): validate_semantic_result(value)
