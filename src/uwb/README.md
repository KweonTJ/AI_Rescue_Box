# UWB

Host ↔ Jetson artifact 통신과 통신 계약만 소유한다.

## Ownership

- `protocol/`: Serial framing, chunking, SHA-256, ACK/NACK, retry, half-duplex, spool core
- `runtime/`: application-facing adapters, Global UWB AI Boost, persistent semantic outbox
- `interfaces/`: JSON Schema와 ROS Interface의 Single Source of Truth
- `ros2_ws/`: UWB bridge/link-level ROS source
- `firmware/`: ESP32 + DWM1000 firmware
- `config/`, `scripts/`, `tests/`: 설정·실행·검증

Astra, RTAB-Map, YOLO/Depth/Risk/Alignment/A*, Jetson 분석 FastAPI와 Flutter는 이 package가 소유하지 않는다.

## Semantic transmission policy

`runtime.ai_boost(...)`가 전송 정책의 명시적 entry point다. 현재는 deterministic policy이며 AI model이 없어도 항상 동작한다.

- `new_victim`, `critical_risk`, `mission_error`: 최고 우선순위
- `route_blocked`: 높은 우선순위
- `semantic_result`: 최초/full semantic state
- `map_delta`: 일반 의미 변화
- `map_preview`: 수동/진단용 낮은 우선순위

정상 제품 흐름은 5~10분 full map snapshot 전송이 아니라 `semantic_result → map_delta / urgent_event` 중심이다. PointCloud/Depth/SLAM DB 원본을 변화마다 전송하지 않는다.

## Persistent Outbox

Jetson semantic artifact는 `AI_RESCUE_DATA_ROOT/uwb_outbox/pending/`에 atomic persist된 뒤 기존 `/uwb/send_artifact` core로 전달된다. `/uwb/queue_artifact`는 기존 `uwb_interfaces/SendArtifact` 계약을 재사용하는 durable application boundary다.

- Host application ACK 전에는 삭제하지 않는다.
- 연결 실패 시 disk에 유지한다.
- process restart 후 metadata/SHA를 검증해 pending을 복구한다.
- reconnect/drain 시 자동 재전송한다.
- content identity가 같은 enqueue는 idempotent하다.
- urgent event는 독립적으로 선행할 수 있지만 같은 mission의 `map_delta`는 result version 순서를 지키며 앞 버전 실패 시 뒤 버전을 보내지 않는다.

## Mission ACK contract

기존 link/application ACK envelope는 유지한다.

- `firmware_frame_ack`
- `peer_stored_ack`
- `application_applied_ack`

Mission artifact의 application ACK는 Jetson application repository에 검증·저장이 끝났음을 뜻한다. 상태 의미는 **STORED/REGISTERED**이며 Tablet ACTIVE 선택과 분리된다.

## Verify

```bash
./scripts/check.sh
```

ROS 2 Humble 환경이 source되어 있으면 `ros2_ws`에서 `colcon build`를 수행한다.
