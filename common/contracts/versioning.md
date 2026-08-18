# Version and ACK Contract

## Independent versions

- `mission_version`: 구조도, 축척, 시작점, 출입구 등 임무 입력
- `slam_map_version`: Live Occupancy/Map 갱신
- `result_version`: Semantic Rescue Map 갱신
- `approved_plan_version`: Host 승인 계획
- `artifact_version`: 전송 단위 버전이며 각 Artifact의 의미 버전과 일치

Version은 1부터 시작하는 증가 정수다. 이미 적용된 Version보다 낮거나 같은 신규 내용은 거절한다. 동일 Version의 동일 SHA-256 재전송은 idempotent 성공으로 처리한다.

## ACK levels

1. `firmware_frame_ack`: ESP32/DWM1000 프레임 수신
2. `peer_stored_ack`: 상대 Bridge가 파일을 검증하고 원자 저장
3. `application_applied_ack`: 수신 애플리케이션이 스키마 검증과 상태 적용을 완료

Mission의 Application ACK는 d_slam이 Mission을 `READY`로 적용한 뒤에만 전송한다. Semantic Result의 Application ACK는 Host가 버전 병합과 UI 반영을 완료한 뒤에만 전송한다.
