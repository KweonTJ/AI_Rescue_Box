# Windows Host product runtime

Windows 10/11에서 **ROS2 없이** Host FastAPI, Flutter Web release, USB Serial UWB를 실행하는 기본 경로다. 외부 FastAPI, Raspberry Pi, 인터넷은 시연 Runtime에 필요하지 않다.

## 1. 준비 및 Web release build

저장소 루트 PowerShell에서 실행한다.

```powershell
.\deploy\host_windows\install.ps1
.\deploy\host_windows\build_web.ps1
```

`install.ps1`은 Python 3.10+ virtualenv, Host package, 공통 UWB protocol, pyserial만 준비한다. Flutter SDK는 `build_web.ps1`을 실행하는 개발/build PC에만 필요하다. 이미 빌드된 `build/web`이 포함된 release bundle의 정상 Runtime에는 Flutter SDK가 필요하지 않다.

장치별 값은 다음 예제를 복사한 뒤 수정한다.

```powershell
Copy-Item .\src\host\config\host.env.example .\src\host\config\host.env
```

`AI_RESCUE_UWB_SERIAL_PORT`에는 Stage 5B에서 확인한 `COM...` 값을 넣는다. 예시 포트를 Production Source에 강제하지 않는다. 포트를 비워도 Host API/Web은 정상 시작하며 UWB 상태만 `serial_disconnected`로 표시된다.

## 2. 시작·상태·종료

```powershell
.\deploy\host_windows\start.ps1
.\deploy\host_windows\status.ps1
.\deploy\host_windows\stop.ps1
```

직접 인자를 줄 수도 있다.

```powershell
.\deploy\host_windows\start.ps1 -UwbPort COM3 -UwbBaud 460800
```

여러 USB Serial 장치 중 **정확히 하나만** 연결된 경우에 한해 `-UwbAutoDiscover`를 사용할 수 있다. 둘 이상이면 임의 선택하지 않고 명시적 포트를 요구한다.

기본 주소:

- UI: `http://127.0.0.1:8000/`
- health: `http://127.0.0.1:8000/api/v1/health`
- status: `http://127.0.0.1:8000/api/v1/status`

로그는 `data/logs/`, PID는 `data/runtime/host.pid`, UWB spool은 `data/uwb_spool/host/`에 저장된다. RGB/Depth frame 원본은 Runtime 로그에 기록하지 않는다.

## 3. Optional ROS2 adapter

기존 Host ROS2 UWB bridge는 삭제하지 않았다. 이미 Windows ROS2 환경을 별도로 준비한 개발 모드에서만 사용한다.

```powershell
.\deploy\host_windows\start.ps1 -EnableRosBridge
```

제품 기본값은 `serial`이며 ROS2 설치는 필수가 아니다. UWB를 전혀 사용하지 않는 로컬 확인은 `-Offline`으로 실행한다.

## 4. Release bundle

```powershell
.\deploy\host_windows\package_release.ps1
```

`dist/ai-rescue-box-host.zip`에는 Host/UWB Python Source, built Web assets, config example, launch scripts와 README가 들어간다. Python 자체를 exe로 freeze하지 않는다.

실제 COM open, ESP32 firmware, DWM1000 Radio와 Host↔Jetson E2E는 `docs/stage5_hardware_validation.md`의 Stage 5B에서 검증한다.
