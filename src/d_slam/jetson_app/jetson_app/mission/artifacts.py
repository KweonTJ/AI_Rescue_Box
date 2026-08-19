from __future__ import annotations
from collections.abc import Mapping, Sequence
from typing import Any
from ..domain import SCHEMA_VERSION, ValidationError, validate_confidence, validate_mission_id, validate_timestamp

def _positive(value: Any, name: str) -> int:
    if isinstance(value,bool) or not isinstance(value,int) or value < 1: raise ValidationError(f"{name} must be a positive integer")
    return value

def _array(value: Any, name: str):
    if not isinstance(value,Sequence) or isinstance(value,(str,bytes)): raise ValidationError(f"{name} must be an array")
    return value

def validate_semantic_result(value: Mapping[str,Any], expected_mission_id: str|None=None) -> dict[str,Any]:
    if not isinstance(value,Mapping): raise ValidationError("semantic_result must be an object")
    result=dict(value)
    if result.get("schema_version") != SCHEMA_VERSION: raise ValidationError("unsupported semantic_result schema_version")
    mission_id=validate_mission_id(result.get("mission_id"))
    if expected_mission_id is not None and mission_id != expected_mission_id: raise ValidationError("semantic_result mission_id does not match active mission")
    result_version=_positive(result.get("result_version"),"result_version"); artifact_version=_positive(result.get("artifact_version",result_version),"artifact_version")
    if artifact_version != result_version: raise ValidationError("artifact_version must match result_version")
    _positive(result.get("base_map_version"),"base_map_version"); _positive(result.get("slam_map_version"),"slam_map_version")
    validate_timestamp(result.get("created_at"),"created_at"); validate_confidence(result.get("confidence"),"confidence")
    if result.get("coordinate_frame") != "mission_map": raise ValidationError("coordinate_frame must be mission_map")
    if result.get("units") not in {"meters","m"}: raise ValidationError("semantic_result units must be meters")
    source=result.get("source")
    if not isinstance(source,str) or not source: raise ValidationError("source must be a non-empty string")
    for field in ("robot_pose","robot_trajectory","victim_candidates","confirmed_victims","obstacles","risk_zones","entry_routes","team_recommendations","safe_waiting_points","explored_areas","unknown_areas"):
        if field not in result: raise ValidationError(f"semantic_result is missing {field}")
        if field != "robot_pose": _array(result[field],field)
    return result

def validate_approved_plan(value: Mapping[str,Any], *, expected_mission_id: str, expected_mission_version: int, expected_result_version: int) -> dict[str,Any]:
    if not isinstance(value,Mapping): raise ValidationError("approved_plan must be an object")
    result=dict(value)
    if result.get("schema_version") != SCHEMA_VERSION: raise ValidationError("unsupported approved_plan schema_version")
    if validate_mission_id(result.get("mission_id")) != expected_mission_id: raise ValidationError("approved_plan mission_id does not match active mission")
    mission_version=_positive(result.get("mission_version",result.get("base_map_version")),"mission_version")
    base_result=_positive(result.get("base_result_version",result.get("semantic_result_version",result.get("based_on_result_version"))),"base_result_version")
    if mission_version != expected_mission_version or base_result != expected_result_version: raise ValidationError("approved_plan references a stale version")
    plan_version=_positive(result.get("approved_plan_version",result.get("plan_version")),"approved_plan_version")
    if _positive(result.get("artifact_version",plan_version),"artifact_version") != plan_version: raise ValidationError("artifact_version must match approved_plan_version")
    if result.get("coordinate_frame","mission_map") != "mission_map": raise ValidationError("coordinate_frame must be mission_map")
    result.setdefault("coordinate_frame","mission_map"); result.setdefault("units","meters"); result.setdefault("source","host_approved"); result.setdefault("confidence",1.0)
    validate_confidence(result["confidence"],"confidence")
    for field in ("approved_victims","excluded_victim_candidates","approved_risk_zones","modified_or_cleared_risk_zones","final_team_assignments","approved_routes","priorities","safe_waiting_points"):
        _array(result.get(field),field)
    return result
