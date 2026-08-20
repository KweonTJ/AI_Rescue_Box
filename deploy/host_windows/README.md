# AI Rescue Box - Windows Host

Windows 10/11에서 **ROS2 없이** Host FastAPI, built Flutter Web, USB Serial UWB를 로컬로 실행하는 제품 경로다. 외부 FastAPI, Raspberry Pi, `doubleclick.lab.cbnu.ac.kr`, 인터넷은 정상 Runtime에 필요하지 않다.

## Quick Start

### 최초 1회

저장소 루트 PowerShell에서 다음 한 줄만 실행한다.

```powershell
.\deploy\host_windows\setup.ps1
```

### 평소 실행

```powershell
.\deploy\host_windows\start.ps1
```

### 종료

```powershell
.\deploy\host_windows\stop.ps1
```

### 상태 확인

```powershell
.\deploy\host_windows\status.ps1
```

정상 사용자는 `install.ps1`, `build_web.ps1`, virtualenv, `pip install`, `flutter build` 명령을 직접 실행할 필요가 없다.

## setup.ps1이 준비하는 것

`setup.ps1`은 기존 Stage 5A 설치/빌드 로직을 새로 복제하지 않고 `install.ps1`과 `build_web.ps1`을 순서대로 호출하는 최초 설치 wrapper다.

- Windows/PowerShell 실행환경과 Python 3.10+ 확인
- 기존 `.venv-host`가 있으면 보존하고 Host/UWB dependency 갱신
- `src/host/config/host.env`가 없을 때만 `host.env.example`을 복사
- `data/host`, `data/logs`, `data/runtime`, `data/uwb_spool/host` 준비
- Flutter SDK 확인 후 Flutter Web release build
- Host/UWB Python import와 `build/web/index.html` sanity check
- UWB Serial 설정 상태 안내

`host.env`가 이미 있으면 절대 덮어쓰지 않는다. 따라서 사용자가 입력한 COM 포트나 다른 장치별 설정은 `setup.ps1`을 다시 실행해도 유지된다. Git pull 후 환경/dependency/Web build를 갱신할 때도 같은 `setup.ps1`을 다시 실행할 수 있다.

## Python / Flutter prerequisite

Python은 **3.10 이상**이 필요하다. Python이 없거나 버전이 낮으면 setup은 어떤 prerequisite가 부족한지 출력하고 중단한다. `winget`이 있으면 Python package 검색 방법도 안내하지만 관리자 권한이나 자동 설치를 강제하지 않는다. Python 설치 후 `setup.ps1`을 다시 실행하면 된다.

최초 Flutter Web release build에는 Flutter stable SDK가 필요하다. `flutter`가 PATH에 없으면 setup은 설치/PATH 설정이 필요하다고 안내하고 중단한다. **setup이 완료된 뒤 정상 `start.ps1` 실행에는 Flutter SDK가 필요하지 않다.** Host FastAPI가 이미 빌드된 Web assets를 serve한다.

## UWB COM 설정

기본 Host 제품 경로는 pure Python Serial UWB다. `host.env`의 기본값은 다음처럼 포트를 비워 둔다.

```text
AI_RESCUE_UWB_SERIAL_PORT=
```

setup 시 실제 ESP32가 연결되어 있지 않아도 전체 Setup은 성공한다. Windows Serial 후보를 조회할 수는 있지만 Bluetooth COM이나 다른 USB Serial을 ESP32라고 추측하지 않으며 **자동으로 host.env에 기록하지 않는다.** 후보가 하나여도 확인용으로만 표시하고, 여러 개면 자동 선택하지 않는다.

실제 Stage 5B에서 ESP32 포트를 확인한 뒤 `src/host/config/host.env`의 `AI_RESCUE_UWB_SERIAL_PORT`를 직접 지정한다. 포트가 비어 있어도 `start.ps1`은 Host API/Web을 정상 실행하며 UWB 상태만 DISCONNECTED로 남는다.

직접 인자를 주는 고급 실행도 유지된다.

```powershell
.\deploy\host_windows\start.ps1 -UwbPort COM3 -UwbBaud 460800
```

여러 USB Serial 장치 중 **정확히 하나만** 연결된 경우에 한해 `-UwbAutoDiscover`를 사용할 수 있다. 둘 이상이면 임의 선택하지 않고 명시적 포트를 요구한다.

기본 주소:

- UI: `http://127.0.0.1:8000/`
- health: `http://127.0.0.1:8000/api/v1/health`
- status: `http://127.0.0.1:8000/api/v1/status`

로그는 `data/logs/`, PID는 `data/runtime/host.pid`, UWB spool은 `data/uwb_spool/host/`에 저장된다. RGB/Depth frame 원본은 Runtime 로그에 기록하지 않는다.

## Advanced / Debug / Manual Setup

기존 Stage 5A 수동 방식은 삭제하지 않고 고급 사용자와 디버깅용으로 유지한다.

```powershell
.\deploy\host_windows\install.ps1
.\deploy\host_windows\build_web.ps1
```

수동 방식에서 `host.env`가 없다면 직접 복사할 수 있다.

```powershell
Copy-Item .\src\host\config\host.env.example .\src\host\config\host.env
```

## Optional ROS2 adapter

기존 Host ROS2 UWB bridge도 그대로 유지한다. 이미 Windows ROS2 환경을 별도로 준비한 개발 모드에서만 사용한다.

```powershell
.\deploy\host_windows\start.ps1 -EnableRosBridge
```

제품 기본값은 `serial`이며 ROS2 설치는 필수가 아니다. UWB를 전혀 사용하지 않는 로컬 확인은 `-Offline`으로 실행한다.

## Release bundle

```powershell
.\deploy\host_windows\package_release.ps1
```

`dist/ai-rescue-box-host.zip`에는 Host/UWB Python Source, built Web assets, config example, `setup.ps1`을 포함한 lifecycle scripts와 README가 들어간다. Python 자체를 exe로 freeze하지 않는다. Bundle에서도 기본 안내는 **최초 `setup.ps1` → 이후 `start.ps1`** 흐름이다.

실제 Windows COM open, ESP32 firmware, DWM1000 Radio와 Host↔Jetson E2E는 이번 UX 작업에서 수행하지 않으며 `docs/stage5_hardware_validation.md`의 Stage 5B에서 검증한다.
