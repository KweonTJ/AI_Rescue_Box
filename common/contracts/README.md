# Common Contracts

이 디렉터리는 Host, UWB와 d_slam 사이의 변경 비용을 제한하기 위한 단일 계약 원본이다.

## Artifact 방향

Host → Jetson:

- `base_map`
- `mission_manifest`
- `approved_plan`

Jetson → Host:

- `semantic_result`
- `map_preview`
- `urgent_event`
- `map_delta`

## 공통 Envelope 원칙

모든 전송 Artifact는 다음 메타데이터를 유지한다.

- `schema_version`
- `mission_id`
- Artifact별 독립 `artifact_version`
- `sha256`
- `source`
- `confidence`
- `coordinate_frame`
- `units`
- 생성 시각

같은 Mission과 같은 Artifact Version에 다른 SHA-256이 들어오면 충돌로 거절한다. 파일 저장 ACK와 Application Applied ACK를 구분한다.

## 구현물

- `schemas/`: 전송 JSON의 기준 스키마
- `python/ai_rescue_contracts`: 의존성 없는 공통 enum과 envelope validation
- `ros2_ws/src/ai_rescue_interfaces`: UWB ↔ d_slam 서비스와 action
- `coordinates.md`: 좌표 변환 규칙
- `versioning.md`: Version과 ACK 규칙
