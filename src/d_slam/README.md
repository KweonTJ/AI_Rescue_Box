# d_slam

Jetson sensor, SLAM, 분석, Local API와 Galaxy Tab client source를 소유한다.

- `astra_camera/`, `astra_camera_msgs/`: Astra RGB-D source
- `d_slam/`: 기존 SLAM/nvblox/RTAB-Map integration
- `jetson_app/`: Mission repository, sensor adapters, YOLO Person+Depth fusion, optional multi-class hazard 후보, risk, Prior↔Live alignment, change/traversability, entry/return route planning, semantic update monitor, FastAPI
- `flutter_app/`: Galaxy Tab Android Mapping App source. SLAM/YOLO/Depth/UWB 연산은 App에서 수행하지 않는다.

## 정상 제품 흐름

```text
Galaxy Tab
구조도 · 축척 · 시작 위치/방향 · 출입구 · Mission
        ↓ Local Network
Jetson
Mission STORED → 명시적 ACTIVE
SLAM · AI · Rescue Map · entry/return route · Safe Zone
        ↓ UWB
Windows Host
Mission/Rescue Map 수신 · 브리핑 · Human-in-the-Loop 수정
```

Tablet이 Mission을 저장하면 Jetson이 구조도와 `mission_manifest`를 durable UWB artifact로 Host에 mirror한다. 기존 Host → Jetson Mission 전송은 개발·백업 경로로 유지한다.

## Global d_slam AI Boost

`jetson_app.ai_boost(...)`가 명시적 entry point다. 별도 `src/ai_boost` package는 만들지 않는다.

현재 검증된 deterministic Stage 4의 alignment, change map, traversability, route evaluation, Safe Zone evaluation을 그대로 사용한다. Optional multi-class RGB hazard model은 `AI_RESCUE_HAZARD_MODEL`로 지정하며, 모델이 없으면 기존 Person+Depth 및 sensor/rule risk가 그대로 동작한다. `structural_damage_candidate`는 붕괴 판정이 아니라 시각적 위험 징후 후보로만 처리한다.

## Mission STORE → ACTIVE

Galaxy Tab Mission 저장 API는 SHA/schema/image 검증 후 `AI_RESCUE_DATA_ROOT/missions/<mission_id>/vN/`에 Mission을 저장하고 `STORED`를 반환한다. 저장과 동시에 Host mirror를 시도하지만 Host/UWB가 없어도 local STORED 상태는 유지한다.

`POST /api/v1/missions/{mission_id}/{mission_version}/select`가 호출될 때만 `current_mission`을 ACTIVE로 지정하고 기존 mission reset 및 Prior Map/alignment 기준을 새 Mission context로 전환한다.

## Entry / Return Route

- `entry_routes`: 출입구 → 요구조자 후보 접근 경로
- `return_routes`: 요구조자 후보 → 출입구 또는 Safe Zone 경로

`return_routes`는 기존 진입 경로 points를 reverse하지 않는다. 최신 occupancy/traversability/change/risk를 사용해 planner를 다시 호출하고 distance/risk/minimum-clearance/confidence/rank를 함께 semantic result에 기록한다.

## Continuous Semantic Update Monitor

ACTIVE Mission이 있을 때만 bounded monitor가 기존 analysis pipeline을 호출한다. 기본 주기는 `AI_RESCUE_SEMANTIC_POLL_SECONDS`로 설정한다.

- 첫 meaningful 분석: `semantic_result`
- stable normalized semantic content가 실제로 바뀐 경우: contiguous `map_delta`
- `new_victim`, `critical_risk`, `route_blocked`, `mission_error`: `urgent_event`
- timestamp/단순 version 변화만 있는 no-op: artifact 없음

`return_routes`도 semantic change key에 포함되어 최신 복귀 경로 변화가 Host reconstruction까지 전달된다.

## Galaxy Tab startup

Tablet은 Jetson FastAPI에서 Mission을 생성/수정/조회한다. 저장된 Mission은 사용자가 명시적으로 선택한 뒤에만 ACTIVE가 되며 Dashboard/운영 화면에서 상태를 확인한다.

## Jetson Local API

```bash
export AI_RESCUE_JETSON_API_HOST=0.0.0.0
export AI_RESCUE_JETSON_API_PORT=8001
export AI_RESCUE_DATA_ROOT="$PWD/data/jetson"
./deploy/jetson/start.sh
```

외부 인터넷/Raspberry Pi/Web server는 실행 조건이 아니다.

## Galaxy Tab APK

```bash
JETSON_API_BASE_URL=http://192.168.50.1:8001 \
  ./deploy/tablet_android/build_apk.sh
```

실제 Jetson/Astra/RTAB-Map/ONNX/Galaxy Tab hardware 성능 및 설치 검증은 실장 검증 범위다.
