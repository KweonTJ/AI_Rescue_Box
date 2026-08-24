# AI Rescue Box

AI Rescue Box는 사고 전 구조도와 재난 후 RGB-D SLAM 지도를 함께 활용해 구조 판단에 필요한 공간정보를 생성하고 제한된 UWB 링크로 전달하는 재난 대응 프로젝트다.

## Source of Truth

`total` 브랜치는 최신 `app`을 기준으로 사업계획서의 최종 제품 흐름을 통합한 브랜치다. Host, UWB 통신, Jetson SLAM/분석, Galaxy Tab client source를 함께 관리하며 제품 runtime은 외부 Raspberry Pi/Web server나 인터넷에 의존하지 않는다.

## Product runtime

```text
Galaxy Tab · Android Mapping App
├── 사고 전 JPG/PNG 구조도
├── 축척 / 시작 위치·방향 / 출입구
└── Mission 생성·Version 저장·ACTIVE 선택
        │ Local REST/WebSocket
        ▼
Jetson Orin Nano · AI Rescue Box
├── Mission 저장/전처리
├── Astra RGB-D / RTAB-Map / Stage 3·4 analysis
├── Prior Map ↔ Live Map alignment / change / traversability
├── Person + Depth 및 optional multi-class hazard 후보
├── entry_routes / independently replanned return_routes / Safe Zone
├── Continuous Semantic Update Monitor
└── Persistent UWB Outbox
        │ Mission mirror / semantic_result / map_delta / urgent_event
        │ ESP32 + DWM1000 · UWB
        ▼
Windows Host PC
├── Mission 자동 등록 + SHA/version 검증
├── Rescue Map reconstruction / briefing
└── Human review → entry/return route, risk, Safe Zone, team → approved_plan
        │
        └── approved_plan → UWB → Jetson
```

- **정상 제품 흐름:** Tablet → Jetson → UWB → Windows Host
- Host → Jetson의 기존 Mission 전송 기능은 개발·복구·백업용으로 유지한다.
- Tablet↔Jetson은 local network, Jetson↔Host 핵심 구조 데이터는 UWB artifact path를 사용한다.
- 외부 인터넷/외부 서버는 정상 동작에 필수 아님
- Jetson Linux UI/VNC는 개발·디버그 선택 사항

## Source layout

```text
src/
├── host/    # Host backend, Flutter Web, semantic reconstruction, review/approval
├── uwb/     # protocol, runtime, contracts, persistent outbox, firmware
└── d_slam/  # Astra, SLAM, Jetson analysis/API and Tablet Flutter
```

`src` 직하위 source package는 위 세 개뿐이다. 통신 계약의 Single Source of Truth는 `src/uwb/interfaces/`다.

Global AI Boost는 네 번째 package가 아니라 각 책임 package 내부의 명시적 entry point다.

- `jetson_app.ai_boost(...)`: deterministic alignment/change/traversability/route/Safe Zone 판단을 보존한다.
- `runtime.ai_boost(...)`: semantic artifact 종류, 우선순위와 경량 전송 정책을 결정한다.
- `host_app.ai_boost(...)`: 이전 semantic state에 `map_delta`를 적용하는 deterministic reconstruction을 보존한다.

AI model이 없거나 optional hazard model이 설정되지 않은 경우에도 기존 Person+Depth 및 rule-based risk/route 기능은 정상 동작한다. 관측되지 않은 공간을 사실처럼 생성하지 않는다.

## Mission lifecycle

Galaxy Tab에서 만든 Mission은 Jetson FastAPI가 SHA/schema/image 검증 후 `missions/<mission_id>/vN/`에 **STORED**한다. 저장된 구조도와 Manifest는 기존 durable UWB artifact 경로를 통해 Host에도 mirror되며 Host는 Mission ID/Version/SHA를 검증해 동일 Version을 중복 생성하지 않는다.

Mission 저장과 운용 적용은 분리된다. 사용자가 Galaxy Tab에서 명시적으로 선택한 뒤에만 해당 Mission이 **ACTIVE**가 되고, 그 시점에 mission reset / Prior Map / 시작 pose / alignment 기준이 적용된다. ACTIVE 상태는 경량 `mission_state`로 Host에 동기화된다.

기존 Host → Jetson Mission 전송 경로는 정상 제품 흐름이 아니라 개발·백업용으로 남긴다.

## Semantic change workflow

Mission이 ACTIVE이면 Jetson의 bounded Continuous Semantic Update Monitor가 기존 Stage 3·4 pipeline을 실행한다.

1. 최초 meaningful state: `semantic_result v1`
2. 이후 실제 의미 변화: `map_delta` (`base_result_version → result_version` 연속)
3. `new_victim`, `critical_risk`, `route_blocked`, `mission_error`: `urgent_event`

Semantic state에는 진입 경로 `entry_routes`와 별도로 최신 Occupancy/Traversability/Risk를 사용해 다시 계산한 `return_routes`를 포함한다. 복귀 경로는 진입 경로의 단순 reverse가 아니다.

단순 timestamp 또는 bare map version 변화는 delta를 만들지 않는다. full RTAB map, PointCloud, Depth 원본, SLAM DB, 고해상도 map image를 매 변화마다 전송하지 않는다. Map Preview는 수동/진단용 저우선순위 artifact다.

Jetson의 `AI_RESCUE_DATA_ROOT/uwb_outbox/`는 artifact를 먼저 atomic persist하고 UWB 전송을 시도한다. Host application ACK가 확인된 항목만 삭제하며, 연결 실패나 process restart 후에도 pending artifact를 복구·drain한다. `map_delta`는 mission별 result version 순서를 보존한다.

Host는 최초 `semantic_result`를 base semantic state로 저장하고 이후 `map_delta`를 누적해 최신 Rescue Map을 재구성한다. stale/duplicate/gap을 구분하며 raw artifact와 derived reconstruction state를 분리한다. 기존 Host review overlay/Undo/Redo/Approved Plan은 source semantic state와 분리되어 유지되며, entry/return route를 승인·제외·수정할 수 있다.

## Quick Start

### Host — Windows

최초 1회:

```powershell
.\deploy\host_windows\setup.ps1
```

이후 실행:

```powershell
.\deploy\host_windows\start.ps1
```

`setup.ps1`은 Python 3.10+, Flutter, dependency/Web build, `host.env` 최초 생성, runtime directory와 sanity check를 담당한다. 기존 `host.env`는 보존하며 Serial port를 임의로 자동 선택하지 않는다. ESP32/UWB가 없어도 Host setup 자체는 가능하고, setup 후 runtime start에는 Flutter SDK가 필수가 아니다.

### Jetson

```bash
python3 -m pip install -e './src/d_slam/jetson_app[api]'
./deploy/jetson/start.sh
```

기본 API bind는 `0.0.0.0:8001`이다. Semantic monitor cadence는 `AI_RESCUE_SEMANTIC_POLL_SECONDS`, UWB outbox drain cadence는 `AI_RESCUE_UWB_OUTBOX_DRAIN_SECONDS`로 조절할 수 있다. Optional multi-class model은 `AI_RESCUE_HAZARD_MODEL`로 지정하며 weight는 저장소에 포함하지 않는다.

### Galaxy Tab

```bash
JETSON_API_BASE_URL=http://192.168.50.1:8001 \
  ./deploy/tablet_android/build_apk.sh
```

Tablet은 로컬 파일 picker에서 JPG/PNG 구조도를 선택하고 Mission/축척/시작 pose/출입구를 Jetson에 저장한다. 저장(STORED)과 ACTIVE 선택은 분리되어 있다.

## Boundary rules

- Host는 d_slam 구현을 직접 import하지 않는다.
- d_slam은 UWB protocol/runtime 구현을 직접 import하지 않는다.
- UWB는 Astra/RTAB-Map/YOLO/Depth/Risk/Alignment/A* 구현을 import하지 않는다.
- package 간 연결은 `src/uwb/interfaces/`의 JSON Schema/ROS Interface와 명시적 Port를 사용한다.
- GO2 low-level autonomous control과 외부 서버 의존은 이 단계에 추가하지 않는다.

## Verification

`total` 브랜치에서는 Mission sync, return route, hazard mapping에 대한 targeted Python test와 Host/Tablet `flutter analyze`를 최소 검증으로 사용한다. 실제 Jetson Orin Nano, Astra RGB-D, RTAB-Map 현장 추적, ONNX inference, ESP32/DWM1000 radio, Galaxy Tab 설치, Windows COM port 및 offline hardware E2E는 별도 실장 검증 범위다.
