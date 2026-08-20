# AI Rescue Box

AI Rescue Box는 사고 전 구조도와 재난 후 RGB-D SLAM 지도를 함께 활용해 구조 판단에 필요한 공간정보를 생성하고 제한된 UWB 링크로 전달하는 재난 대응 프로젝트다.

## Source of Truth

`app` 브랜치가 Host, UWB 통신, Jetson SLAM/분석, Galaxy Tab client source의 단일 Source of Truth다. 제품 runtime은 외부 Raspberry Pi/Web server나 인터넷에 의존하지 않는다.

## Product runtime

```text
Windows Host PC
├── Host FastAPI / Flutter Web
├── Prior Map + semantic state reconstruction / human review
└── Host UWB Bridge
        │ Mission / semantic_result / map_delta / urgent_event / approved_plan
        │ ESP32 + DWM1000
        ▼
Jetson Orin Nano
├── Astra RGB-D / RTAB-Map / Stage 3·4 analysis
├── Prior Map ↔ Live Map alignment / change / traversability / planning
├── Continuous Semantic Update Monitor
├── Persistent UWB Outbox
└── Jetson FastAPI
        │ Local Wi-Fi / Jetson hotspot / USB Network / LAN
        ▼
Galaxy Tab
└── Mission Selector → Dashboard Android APK
```

- Host↔Jetson 핵심 구조 데이터: UWB artifact path
- Tablet↔Jetson: local REST/WebSocket
- 외부 인터넷/외부 서버: 정상 동작에 필수 아님
- Jetson Linux UI/VNC: 개발·디버그 선택 사항

## Source layout

```text
src/
├── host/    # Host backend, Flutter Web, semantic reconstruction, review/approval
├── uwb/     # protocol, runtime, contracts, persistent outbox, firmware
└── d_slam/  # Astra, SLAM, Jetson analysis/API and Tablet Flutter
```

`src` 직하위 source package는 위 세 개뿐이다. 통신 계약의 Single Source of Truth는 `src/uwb/interfaces/`다.

Global AI Boost는 네 번째 package가 아니라 각 책임 package 내부의 명시적 entry point다.

- `jetson_app.ai_boost(...)`: 기존 deterministic alignment/change/traversability/route/Safe Zone 판단을 보존하며 향후 AI advisory를 연결한다.
- `runtime.ai_boost(...)`: semantic artifact 종류, 우선순위와 경량 전송 정책을 결정한다.
- `host_app.ai_boost(...)`: Prior Map과 이전 semantic state에 `map_delta`를 적용하는 deterministic reconstruction을 보존한다.

AI model이 없거나 `enabled=False`인 경우 모두 deterministic fallback으로 기존 기능이 정상 동작한다. 관측되지 않은 공간을 사실처럼 생성하지 않는다.

## Mission lifecycle

Host가 UWB로 보낸 Mission은 Jetson에서 SHA/schema/image 검증 후 `missions/<mission_id>/vN/`에 **STORED**된다. 수신만으로 `current_mission`을 바꾸거나 d_slam을 reset/시작하지 않는다.

Galaxy Tab APK는 cold launch 때 항상 Mission Selector를 먼저 표시한다. 저장된 Mission을 FastAPI로 조회하고 사용자가 명시적으로 선택한 뒤에만 해당 Mission이 **ACTIVE**가 되며, 그 시점에 기존 mission reset / Prior Map / 시작 pose / alignment 기준이 적용된다.

## Semantic change workflow

Mission이 ACTIVE이면 Jetson의 bounded Continuous Semantic Update Monitor가 기존 Stage 3·4 pipeline을 실행한다.

1. 최초 meaningful state: `semantic_result v1`
2. 이후 실제 의미 변화: `map_delta` (`base_result_version → result_version` 연속)
3. `new_victim`, `critical_risk`, `route_blocked`, `mission_error`: `urgent_event`

단순 timestamp 또는 bare map version 변화는 delta를 만들지 않는다. full RTAB map, PointCloud, Depth 원본, SLAM DB, 고해상도 map image를 매 변화마다 전송하지 않는다. Map Preview는 수동/진단용 저우선순위 artifact다.

Jetson의 `AI_RESCUE_DATA_ROOT/uwb_outbox/`는 artifact를 먼저 atomic persist하고 UWB 전송을 시도한다. Host application ACK가 확인된 항목만 삭제하며, 연결 실패나 process restart 후에도 pending artifact를 복구·drain한다. `map_delta`는 mission별 result version 순서를 보존한다.

Host는 최초 `semantic_result`를 base semantic state로 저장하고 이후 `map_delta`를 `host.ai_boost()`를 통해 누적해 최신 Rescue Map을 재구성한다. stale/duplicate/gap을 구분하며 raw artifact와 derived reconstruction state를 분리한다. 기존 Host review overlay/Undo/Redo/Approved Plan은 source semantic state와 분리되어 새 delta가 와도 조용히 사라지지 않으며, source entity가 사라진 편집은 conflict event로 표시한다.

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

기본 API bind는 `0.0.0.0:8001`이다. Semantic monitor cadence는 `AI_RESCUE_SEMANTIC_POLL_SECONDS`, UWB outbox drain cadence는 `AI_RESCUE_UWB_OUTBOX_DRAIN_SECONDS`로 조절할 수 있다.

### Galaxy Tab

```bash
JETSON_API_BASE_URL=http://192.168.50.1:8001 \
  ./deploy/tablet_android/build_apk.sh
```

APK는 Jetson의 저장된 Mission만 API로 조회하며 Android local file picker나 Jetson 임의 filesystem browser를 사용하지 않는다.

## Boundary rules

- Host는 d_slam 구현을 직접 import하지 않는다.
- d_slam은 UWB protocol/runtime 구현을 직접 import하지 않는다.
- UWB는 Astra/RTAB-Map/YOLO/Depth/Risk/Alignment/A* 구현을 import하지 않는다.
- package 간 연결은 `src/uwb/interfaces/`의 JSON Schema/ROS Interface와 명시적 Port를 사용한다.
- GO2 low-level autonomous control과 외부 서버 의존은 이 단계에 추가하지 않는다.

## Verification

CI는 repository/contract/legacy/import boundary, Python compile/test, Stage2~5 regression, PowerShell parser, Host Flutter Web, Tablet Flutter/debug APK, ESP32 firmware compile을 수행한다. ROS2가 없는 CI runner의 ROS build는 기존 정책대로 명시적으로 skip된다.

실제 Jetson Orin Nano, Astra RGB-D, RTAB-Map 현장 추적, ONNX inference, ESP32/DWM1000 radio, Galaxy Tab 설치, Windows COM port 및 hotspot/offline hardware E2E는 별도 Stage 5B 실장 검증 범위다.
