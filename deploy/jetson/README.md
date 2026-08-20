# Jetson Orin Nano product deployment

이 디렉터리는 기존 Astra/RTAB-Map/d_slam, Mission service, Stage 2 UWB 경로, Stage 3/4 Jetson API를 새 framework 없이 묶는다. Stage 5A에서는 설치·build·launch 코드를 준비할 뿐 실제 장치를 실행하거나 검증하지 않는다.

## 1. 환경 확인·Python 설치·ROS build

```bash
cd ~/AI_Rescue_Box
git switch app
git pull --ff-only origin app
./deploy/jetson/install.sh
```

`install.sh`은 다음을 수행한다.

- Python 3.10+ `--system-site-packages` virtualenv 생성
- `jetson_app`, 공통 UWB protocol, pyserial 설치
- data/log/runtime/spool directory 생성
- ROS2, colcon, RTAB-Map, Python OpenCV/numpy 상태 확인
- 기존 Astra/d_slam/UWB/interface Source를 하나의 colcon install space로 build
- 모델·machine config 누락을 `WAITING`으로 표시

ROS2, CUDA, Astra driver, RTAB-Map을 인터넷에서 무조건 설치하지 않는다. 준비 상태만 확인하고 누락 항목을 명시한다. 현재 환경을 변경하지 않고 검사만 하려면 다음을 사용한다.

```bash
./deploy/jetson/install.sh --check-only
```

## 2. 장치별 config

```bash
cp src/d_slam/config/jetson.env.example src/d_slam/config/jetson.env
cp src/uwb/config/jetson.env.example src/uwb/config/jetson.env
```

반드시 Stage 5B에서 실제 값으로 설정할 항목:

- `AI_RESCUE_YOLO_MODEL`
- `AI_RESCUE_UWB_SERIAL_PORT` (`/dev/ttyUSB*`, `/dev/ttyACM*` 또는 확인된 udev symlink)
- Astra/RTAB topic과 TF frame이 기본값과 다른 경우 해당 topic/frame
- 필요한 경우 `AI_RESCUE_JETSON_CONFIG` 복사본의 Stage 4 alignment search/confidence 값
- Hotspot SSID/password/interface/address

포트를 비우면 UWB bridge는 종료되지 않고 `serial_unconfigured` 상태로 기동한다. VID/PID는 추측하지 않는다.

## 3. 전체 stack 시작·상태·종료

ROS2 환경을 source한 shell에서 실행한다.

```bash
./deploy/jetson/start.sh
./deploy/jetson/status.sh
./deploy/jetson/stop.sh
```

`start.sh`가 기존 entry point를 다음 순서로 실행하고 PID/log를 관리한다.

1. `ros2 launch d_slam d_slam.launch.py` — Astra + RGB-D sync + visual odometry + RTAB-Map
2. `python -m jetson_app.mission.ros_server` — Mission/Approved Plan application services
3. `ros2 run uwb_jetson_bridge jetson_bridge` — 기존 Stage 2 protocol + reconnectable Serial transport
4. `python -m runtime.jetson_stage2_node` — UWB artifact ↔ d_slam service/result return 연결
5. `python -m jetson_app.api` — Stage 3/4 analysis와 Tablet API

기본 API는 `0.0.0.0:8001`에 bind한다. 로그는 `data/logs/jetson/`, PID는 `data/runtime/jetson/`, UWB spool은 `data/uwb_spool/jetson/`에 있다. 대용량 RGB/Depth frame은 로그에 저장하지 않는다.

`status.sh`의 `WAITING`/`DISCONNECTED`는 장치가 없을 때 정상이다. `RUNNING`은 프로세스 상태일 뿐 Astra stream, RTAB tracking, DWM1000 Radio 성공을 의미하지 않는다.

## 4. Tablet network

Runtime은 외부 인터넷이나 외부 서버 없이 다음 세 방식으로 접근 가능하다.

- Jetson Wi-Fi Hotspot: 권장 시연 방식
- USB network: Jetson/Tablet가 지원하는 USB tether/network 구성
- 같은 LAN

Hotspot 설정 내용을 먼저 확인한다. 이 명령은 network를 변경하지 않는다.

```bash
./deploy/jetson/network/hotspot.sh plan
```

Stage 5B에서 password/interface를 설정한 뒤에만 명시적으로 실행한다.

```bash
./deploy/jetson/network/hotspot.sh up
./deploy/jetson/network/hotspot.sh status
```

예시 gateway `192.168.50.1`은 config 기본값일 뿐 Source 깊숙이 강제되지 않는다. Tablet APK URL도 build-time `--dart-define`으로 변경한다.

## 5. udev와 systemd

- `udev/99-ai-rescue-uwb.rules.example`: 실제 ESP32 VID/PID 확인 후 편집하는 **비활성 template**
- `systemd/ai-rescue-box.service.example`: 저장소 경로와 User를 편집한 뒤 검토하는 optional full-stack service

Stage 5A에서는 규칙을 설치하지 않고 `systemctl enable`도 실행하지 않는다. 수동 `start.sh`가 MVP 기본 경로다.

실장 순서와 측정 기록은 `docs/stage5_hardware_validation.md` 및 `docs/stage5_measurement_template.md`를 따른다.
