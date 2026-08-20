# d_slam

Jetson sensor, SLAM, 분석, Local API와 Galaxy Tab client source를 소유한다.

- `astra_camera/`, `astra_camera_msgs/`: Astra RGB-D source
- `d_slam/`: 기존 SLAM/nvblox/RTAB-Map integration
- `jetson_app/`: Mission repository, sensor adapters, YOLO person+Depth fusion, risk, Prior↔Live alignment, change/traversability/planning, semantic update monitor, FastAPI
- `flutter_app/`: Galaxy Tab Android APK source. SLAM/YOLO/Depth/UWB 연산은 APK에서 수행하지 않는다.

## Global d_slam AI Boost

`jetson_app.ai_boost(...)`가 명시적 entry point다. 별도 `src/ai_boost` package는 만들지 않는다.

현재 검증된 deterministic Stage 4의 alignment, change map, traversability, route evaluation, Safe Zone evaluation을 entry point 뒤에서 그대로 사용한다. `enabled=False` 또는 model unavailable이면 deterministic 결과를 반환한다. observed/unknown/prior evidence를 보존하며 관측되지 않은 공간을 사실처럼 생성하지 않는다.

## Mission STORE → ACTIVE

UWB `LoadMission`은 SHA/schema/image 검증 후 `AI_RESCUE_DATA_ROOT/missions/<mission_id>/vN/`에 Mission을 저장하고 `STORED`를 반환한다. 이 단계에서는 `current_mission.json` 변경, d_slam reset, Prior Map 적용, 분석 시작을 하지 않는다.

Galaxy Tab에서 `POST /api/v1/missions/{mission_id}/{mission_version}/select`가 호출될 때만 `current_mission`을 ACTIVE로 지정하고 기존 mission reset 및 Prior Map/alignment 기준을 새 Mission context로 전환한다.

## Continuous Semantic Update Monitor

ACTIVE Mission이 있을 때만 bounded monitor가 기존 analysis pipeline을 호출한다. 기본 주기는 `AI_RESCUE_SEMANTIC_POLL_SECONDS`로 설정한다.

- 첫 meaningful 분석: `semantic_result`
- stable normalized semantic content가 실제로 바뀐 경우: contiguous `map_delta`
- `new_victim`, `critical_risk`, `route_blocked`, `mission_error`: `urgent_event`
- timestamp/단순 version 변화만 있는 no-op: artifact 없음

자동 전송은 UWB의 durable `/uwb/queue_artifact` boundary를 사용한다. 기존 Tablet의 결과/Preview 전송 기능은 진단·수동 재전송 용도로 유지할 수 있으며 정상 semantic update 흐름은 버튼에 의존하지 않는다.

## Galaxy Tab startup

APK cold launch는 항상 Dashboard가 아니라 Mission Selector로 시작한다. Jetson FastAPI에 저장된 Mission만 조회하며 Android local file picker나 `/etc`, `/home`, `/usr` 같은 Jetson filesystem browser를 사용하지 않는다.

Mission card는 Mission 이름/ID/version, verification/received 시각, 현재 사용 중 여부를 표시한다. 저장 Mission이 없으면 `Host에서 수신한 구조도가 없습니다.`를 표시하며 API 연결 실패 시 주소와 재시도 UI를 제공한다. 사용자가 Mission을 선택한 뒤에만 Dashboard로 이동하고 Dashboard에서 `다른 구조도 선택`으로 selector에 돌아갈 수 있다.

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

실제 Jetson/Astra/RTAB-Map/ONNX/Galaxy Tab hardware 성능 및 설치 검증은 Stage 5B 범위다.
