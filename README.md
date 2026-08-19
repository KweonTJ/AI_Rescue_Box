# AI Rescue Box

AI Rescue Box는 사고 전 구조도와 재난 후 RGB-D SLAM 지도를 함께 활용해 구조 판단에 필요한 공간정보를 생성하고 제한된 UWB 링크로 전달하는 재난 대응 프로젝트다.

## Source of Truth

`app` 브랜치 하나가 Host, UWB 통신, Jetson SLAM/분석, Galaxy Tab client source의 단일 Source of Truth다. 별도 `rescue_app`, `raspberrypi_server`, Raspberry Pi 파일 또는 특정 외부 Web server를 제품 Runtime/Build 원본으로 사용하지 않는다.

Stage 0·1의 계약/책임 분리를 유지하며 Stage 1.5는 실행 플랫폼과 외부 서버 의존만 정리한다. 실제 Host→UWB→Jetson Mission application flow는 아직 연결하지 않는다.

## Product runtime

```text
Windows Host PC
├── Host FastAPI / Backend
├── Flutter Web (Chrome / Edge)
└── Host UWB Bridge source
        │ UWB
        ▼
Jetson Orin Nano
├── Jetson Local FastAPI
├── d_slam / Astra / RTAB-Map
├── existing analysis runtime
└── Jetson UWB runtime source
        │ Local Wi-Fi / USB Network / LAN
        ▼
Galaxy Tab
└── AI Rescue Box Android APK
```

- Host↔Jetson 핵심 구조 데이터 링크: UWB
- Tablet↔Jetson UI 링크: Local REST/WebSocket
- 외부 인터넷/외부 서버: 제품 동작에 필수 아님
- Jetson Linux UI/VNC: 개발·디버그 선택 사항

## Source layout

```text
src/
├── host/    # Host backend, Flutter Web, Host UWB bridge, review/approval
├── uwb/     # protocol, runtime wrappers, schemas/ROS interfaces, firmware
└── d_slam/  # Astra, SLAM, Jetson Local API/analysis and Tablet Flutter
```

`src` 직하위의 기능 책임은 위 세 디렉터리뿐이다. 통신 계약의 Single Source of Truth는 `src/uwb/interfaces`다.

## Quick Start

### Host — Windows

PowerShell에서 저장소 루트 기준:

```powershell
.\deploy\host_windows\install.ps1
.\deploy\host_windows\build_web.ps1
.\deploy\host_windows\start.ps1
```

Chrome/Edge에서 `http://127.0.0.1:8000/`을 사용한다. FastAPI가 빌드된 Flutter Web을 직접 제공하며 기본 실행은 ROS/UWB가 없어도 가능한 offline bridge mode다.

### Jetson

기존 Jetson/Astra/SLAM 의존성을 준비한 뒤 Local API package를 설치하고 실행한다.

```bash
python3 -m pip install -e './src/d_slam/jetson_app[api]'
./deploy/jetson/start.sh
```

기본 bind는 `0.0.0.0:8001`이다. Jetson 내부에서는 `http://127.0.0.1:8001/api/v1/health`, Tablet에서는 실제 Jetson 로컬 IP로 health를 확인한다.

### Galaxy Tab

```bash
JETSON_API_BASE_URL=http://192.168.50.1:8001 \
  ./deploy/tablet_android/build_apk.sh
```

생성된 debug APK를 설치하고 Tab을 Jetson hotspot/USB Network/같은 LAN에 연결한다. API 주소는 build-time `JETSON_API_BASE_URL` 하나로 변경한다.

## Boundary rules

- Host는 d_slam 구현을 직접 import하지 않는다.
- d_slam은 UWB protocol/runtime 구현을 직접 import하지 않는다.
- UWB는 d_slam의 Sensor/SLAM/YOLO 구현을 import하지 않는다.
- 패키지 간 연결은 JSON Schema, ROS Interface 또는 명시된 Port를 사용한다.
- AI 보완 코드는 별도 공통 패키지가 아니라 각 책임 패키지의 실제 기능 안에 둔다.

## Verification

```bash
python3 scripts/check_repository_structure.py
python3 scripts/check_legacy_strings.py
python3 scripts/check_import_boundaries.py
python3 -m compileall -q src
python3 -m pytest -q src/host/tests
python3 -m pytest -q src/uwb/tests
python3 -m pytest -q src/d_slam/tests
```

Flutter verification:

```bash
cd src/host/flutter_app && flutter analyze && flutter test && flutter build web
cd ../../d_slam/flutter_app && flutter analyze && flutter test
```

Tablet debug APK는 `deploy/tablet_android/build_apk.sh`로 검증한다. ROS/hardware E2E는 Stage 1.5 완료 조건이 아니다.
