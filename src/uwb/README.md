# UWB

Host ↔ Jetson artifact 통신과 통신 계약만 소유한다.

## Ownership

- `protocol/`: Serial framing, chunking, SHA-256, ACK/NACK, retry, half-duplex, spool core
- `runtime/`: application-facing adapters, transfer policy, persistent semantic outbox
- `interfaces/`: JSON Schema와 ROS Interface의 Single Source of Truth
- `ros2_ws/`: UWB bridge/link-level ROS source
- `firmware/`: ESP32 + DWM1000 firmware
- `config/`, `scripts/`, `tests/`: 설정·실행·검증

Astra, RTAB-Map, YOLO/Depth/Risk/Alignment/A*, Jetson 분석 FastAPI와 Flutter는 이 package가 소유하지 않는다.

## Product artifact direction

정상 제품 흐름은 다음과 같다.

```text
Tablet → Jetson
Jetson → Host : base_map + mission_manifest, semantic_result, map_delta, urgent_event
Host → Jetson : approved_plan
```

기존 Host → Jetson의 `base_map` + `mission_manifest` 전송은 개발·백업용으로 유지한다. 새로운 protocol을 만들지 않고 동일 artifact kind, SHA-256, persistent outbox, ACK/NACK/retry 계약을 양방향으로 재사용한다.

## Semantic transmission policy

- `new_victim`, `critical_risk`, `mission_error`: 최고 우선순위
- `route_blocked`: 높은 우선순위
- `semantic_result`: 최초/full semantic state (`entry_routes` + `return_routes` 포함)
- `map_delta`: 일반 의미 변화
- `map_preview`: 수동/진단용 낮은 우선순위

정상 제품 흐름은 full map snapshot 반복 전송이 아니라 `semantic_result → map_delta / urgent_event` 중심이다. PointCloud/Depth/SLAM DB 원본을 변화마다 전송하지 않는다.

## Persistent Outbox

Jetson artifact는 `AI_RESCUE_DATA_ROOT/uwb_outbox/pending/`에 atomic persist된 뒤 기존 `/uwb/send_artifact` core로 전달된다. `/uwb/queue_artifact`는 기존 `uwb_interfaces/SendArtifact` 계약을 재사용하는 durable application boundary다.

- Host application ACK 전에는 삭제하지 않는다.
- 연결 실패 시 disk에 유지한다.
- process restart 후 metadata/SHA를 검증해 pending을 복구한다.
- reconnect/drain 시 자동 재전송한다.
- content identity가 같은 enqueue는 idempotent하다.
- 같은 mission의 `map_delta`는 result version 순서를 지킨다.

## Mission ACK contract

기존 link/application ACK envelope를 유지한다.

- `firmware_frame_ack`
- `peer_stored_ack`
- `application_applied_ack`

Jetson → Host Mission mirror에서 `base_map` application ACK는 Host staging 저장 완료, `mission_manifest` application ACK는 SHA/Version 검증과 Host Mission 등록 완료를 의미한다. 같은 Mission Version/동일 내용은 ACK 가능한 duplicate이며 다른 내용이면 NACK한다.

## Verify

변경 기능은 mock/loopback artifact test로 검증하고 실제 ESP32/DWM1000 radio는 hardware validation에서 확인한다.
