# Windows Host

대회/제품 기본 Host 경로다. 별도 Raspberry Pi나 외부 Web server가 필요하지 않다.

## Requirements

- Windows 10/11
- Python 3.10+
- Flutter SDK with Web support
- Chrome 또는 Edge

ROS2/UWB는 이 기본 설치의 필수 조건이 아니다.

## Quick start

저장소 루트 PowerShell에서 실행한다.

```powershell
.\deploy\host_windows\install.ps1
.\deploy\host_windows\build_web.ps1
.\deploy\host_windows\start.ps1
```

기본 주소:

- Host UI: `http://127.0.0.1:8000/`
- Host API health: `http://127.0.0.1:8000/api/v1/health`

FastAPI가 `src/host/flutter_app/build/web`을 직접 서빙하므로 별도 Web server 프로세스가 필요 없다.

## Existing UWB bridge

기본은 `offline`이며 UWB/ROS2가 없어도 Backend/Web을 사용할 수 있다. 이미 Windows ROS2 + Host UWB bridge 환경이 준비된 경우에만:

```powershell
.\deploy\host_windows\start.ps1 -EnableRosBridge
```

Stage 1.5는 ROS2 설치, 실제 UWB E2E 연결, system service 설정을 수행하지 않는다.

## Optional remote/demo profile

외부 서버를 사용할 필요가 있다면 `build_web.ps1 -ApiBaseUrl <HTTPS API URL>`처럼 별도 build-time API를 지정할 수 있다. 이 경로는 제품 기본값이 아니다.
