# Host

Windows 지휘소에서 실행하는 Host 책임 소스다.

## Ownership

- `host_app/`: FastAPI, 구조도 등록·검증·정규화, Mission/Store, Semantic Result/Map Preview 수신과 검토, Approved Plan 생성
- `flutter_app/`: Chrome/Edge에서 사용하는 Flutter Web Source
- `ros2_ws/src/uwb_host_bridge/`: Host 측 UWB ROS bridge source
- `config/`: Host 로컬 실행 예시 설정
- `scripts/`: 기존 Host build/run/check
- `tests/`: Host Unit/Mock

통신 계약은 `../uwb/interfaces`가 Single Source of Truth다. Host는 d_slam 구현을 직접 import하지 않는다.

## Windows product path

기본 제품 실행은 ROS2/UWB 장치가 없어도 Backend/Web이 먼저 뜨는 `offline` bridge mode다.

```powershell
.\deploy\host_windows\install.ps1
.\deploy\host_windows\build_web.ps1
.\deploy\host_windows\start.ps1
```

`build_web.ps1`가 만든 `flutter_app/build/web`을 Host FastAPI가 `/`에서 직접 제공하므로 기본 UI/API 주소는 하나다.

- UI: `http://127.0.0.1:8000/`
- API: `http://127.0.0.1:8000/api/v1/...`

Host Flutter Web은 브라우저에서 실행될 때 same-origin을 기본 API로 사용한다. 별도 Flutter 개발 서버를 사용할 때만 `--dart-define=API_BASE_URL=http://127.0.0.1:8000`처럼 명시한다.

실제 Host UWB ROS bridge를 쓸 환경에서는 `AI_RESCUE_UWB_BRIDGE_MODE=ros` 또는 Windows start script의 `-EnableRosBridge`를 사용한다. Stage 1.5에서는 Windows용 ROS2 설치를 자동화하지 않는다.

## Verify

```bash
./scripts/check.sh
```

Flutter는 `flutter_app`에서 `flutter analyze`, `flutter test`, `flutter build web`으로 확인한다.
