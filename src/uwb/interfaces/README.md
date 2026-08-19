# Communication Interfaces

`src/uwb/interfaces`는 Host ↔ UWB ↔ Jetson 사이에서 공유되는 통신 계약의 Single Source of Truth다. Stage 0·1에서는 계약과 소스 위치만 확정하며 실제 Mission 적용 서버 동작은 구현하지 않는다.

## JSON schemas

- `schemas/mission_manifest.schema.json`
- `schemas/semantic_result.schema.json`
- `schemas/approved_plan.schema.json`
- `schemas/map_delta.schema.json`
- `schemas/urgent_event.schema.json`

## ROS interfaces

- `ros2/ai_rescue_interfaces/srv/LoadMission.srv`
- `ros2/ai_rescue_interfaces/srv/ApplyApprovedPlan.srv`
- `ros2/ai_rescue_interfaces/srv/MissionControl.srv`
- `ros2/ai_rescue_interfaces/action/SubmitRescueUpdate.action`

## Coordinate frames

- `image_px`: 원본 구조도 픽셀 좌표
- `mission_map`: Host 구조도를 meter 단위로 정규화한 외부 계약 좌표계
- `slam_map`: RTAB-Map의 live map 좌표계
- camera optical frame: RGB-D 역투영 입력 좌표계
- `T_mission_map_from_slam_map`: slam 결과를 mission 좌표로 변환하는 2D rigid transform

세부 규칙은 `coordinates.md`를 따른다.

## Version fields

각 artifact는 의미에 맞는 버전을 명시한다.

- `mission_version`
- `slam_map_version`
- `result_version`
- `approved_plan_version`
- `artifact_version`

오래된 버전이 최신 상태를 덮어쓰지 않도록 validator와 runtime 저장 계층이 동일한 양의 정수 규칙을 사용한다. 세부 의미는 `versioning.md`를 따른다.

## ACK layers

전송 성공을 한 단계의 boolean으로 축약하지 않는다.

1. `firmware_frame_ack`: 개별 UWB frame 전달 확인
2. `peer_stored_ack`: peer가 artifact 전체를 검증하고 저장했음을 확인
3. `application_applied_ack`: application이 artifact를 검증하고 적용했음을 확인

Stage 0·1에서는 이 명칭과 의미만 계약으로 고정한다.
