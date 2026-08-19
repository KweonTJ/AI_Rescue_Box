from host_app.mission.models import SemanticResult, ValidationError

def payload(): return {'schema_version':'1.0','mission_id':'mission-1','base_map_version':1,'slam_map_version':1,'result_version':1,'artifact_version':1,'created_at':'2026-08-19T00:00:00Z','coordinate_frame':'mission_map','units':'meters','source':'jetson_sensor_analysis','confidence':0.8,'analysis_mode':'real','robot_pose':{'x':0.0,'y':0.0,'yaw':0.0},'robot_trajectory':[],'victim_candidates':[],'confirmed_victims':[],'obstacles':[],'risk_zones':[],'entry_routes':[],'team_recommendations':[],'safe_waiting_points':[],'explored_areas':[],'unknown_areas':[]}
def test_host_accepts_stage0_semantic_contract():
    validated=SemanticResult.validate(payload(),'mission-1'); assert validated['analysis_mode']=='real' and validated['team_recommendations']==[]
def test_host_rejects_non_mission_map_result():
    value=payload(); value['coordinate_frame']='slam_map'
    try: SemanticResult.validate(value,'mission-1')
    except ValidationError: return
    raise AssertionError('slam_map external result must be rejected')
