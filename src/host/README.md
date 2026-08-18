# AI Rescue Box Host Flutter + UWB Runtime

Basecamp Host PC에서 AI Rescue Box의 **구조도 등록, 최초 임무 전송, Jetson 분석 결과 검토, 최종 구조계획 승인**을 수행하는 실행 패키지다. Host Flutter UI, Host FastAPI backend, Host UWB ROS 2 Bridge와 공통 artifact protocol을 한 폴더에서 준비·빌드·실행한다.

```text
PC / Phone Browser
        ↓ HTTPS
Raspberry Pi Host Flutter Web
        ↓ REST + WebSocket
Host PC 192.168.0.10:8000
        ↓ local ROS 2
Host UWB Bridge
        ↓ USB Serial 460800 baud
ESP32 + DWM1000
        ↕ UWB half-duplex
Jetson ESP32 + DWM1000
        ↓
Jetson UWB Bridge → Jetson FastAPI / SLAM / Analysis
```

Flutter와 FastAPI는 ESP32 Serial을 직접 열지 않는다. `/dev/ttyACM*`, packet chunk, ACK, 재전송과 spool 관리는 `uwb_host_bridge`가 단독으로 담당한다.

## 폴더 구조

```text
AI_Rescue_Box/src/host/
├── README.md
├── requirements.txt
├── prepare_from_rescue_app.sh
├── config/
│   └── host.env.example
├── scripts/
│   ├── _runtime_env.sh
│   ├── build.sh
│   ├── check.sh
│   ├── run_host_api_offline.sh
│   ├── run_host_api_real.sh
│   ├── run_host_flutter_web.sh
│   ├── run_uwb_bridge.sh
│   └── verify_package.py
├── host_app/                         # prepare 실행 후 생성
│   ├── host_app/
│   └── flutter_app/
├── flutter_shared/                   # prepare 실행 후 생성
├── common/ai_rescue_uwb_common/      # prepare 실행 후 생성
└── ros2_ws/src/                      # prepare 실행 후 생성
    ├── ai_rescue_uwb_common/
    ├── uwb_interfaces/
    └── uwb_host_bridge/
```

Jetson 분석·SLAM·센서 코드, `uwb_jetson_bridge`, ESP32 firmware, 테스트, Flutter의 불필요한 플랫폼 scaffold와 build 결과는 포함하지 않는다.

## 1. 저장소 받기

```bash
cd ~
git clone git@github.com:Jeong-Yun-Kim/AI_Rescue_Box.git
cd ~/AI_Rescue_Box
```

이미 받은 저장소는 다음처럼 최신화한다.

```bash
cd ~/AI_Rescue_Box
git switch main
git pull --ff-only origin main
```

## 2. 시스템 준비

Ubuntu 22.04와 ROS 2 Humble이 설치되어 있다는 전제다.

```bash
sudo apt update
sudo apt install -y \
  python3-venv python3-pip python3-rosdep \
  python3-colcon-common-extensions rsync
```

이 PC에서 `rosdep`을 처음 사용할 때만:

```bash
sudo rosdep init
rosdep update
```

Serial 권한:

```bash
sudo usermod -aG dialout "$USER"
```

적용하려면 로그아웃 후 다시 로그인한다.

## 3. 실행 소스 준비

이 패키지는 `Jeong-Yun-Kim/rescue_app`에서 Host 실행에 필요한 소스만 선별해 현재 폴더에 배치한다.

```bash
# ~/rescue_app이 없다면 한 번만
cd ~
git clone git@github.com:Jeong-Yun-Kim/rescue_app.git

# Host package 생성/갱신
cd ~/AI_Rescue_Box/src/host
./prepare_from_rescue_app.sh ~/rescue_app
python3 scripts/verify_package.py
```

`rescue_app`이 이미 있다면 최신화 후 prepare만 다시 실행한다.

```bash
cd ~/rescue_app
git pull --ff-only origin main
cd ~/AI_Rescue_Box/src/host
./prepare_from_rescue_app.sh ~/rescue_app
```

## 4. 환경 설정

기본값과 다를 때만 example을 복사한다.

```bash
cd ~/AI_Rescue_Box/src/host
cp config/host.env.example config/host.env
nano config/host.env
```

기본값:

| 항목 | 값 |
| --- | --- |
| Host PC IP | `192.168.0.10` |
| FastAPI | `0.0.0.0:8000` |
| 로컬 Flutter Web | `0.0.0.0:8080` |
| 공개 Flutter | `https://doubleclick.lab.cbnu.ac.kr/rescue/host/` |
| UWB Serial | `/dev/ttyACM0` |
| baudrate | `460800` |
| ROS local IPC | `ROS_LOCALHOST_ONLY=1` |

## 5. 설치 및 빌드

```bash
cd ~/AI_Rescue_Box
./src/host/scripts/build.sh
./src/host/scripts/check.sh
```

`build.sh`는 `.venv_host`를 만들고 Host FastAPI package, `ai_rescue_uwb_common`, `uwb_interfaces`, `uwb_host_bridge`를 빌드한다.

## 6. UWB 없이 Host 앱/API 확인

```bash
cd ~/AI_Rescue_Box
./src/host/scripts/run_host_api_offline.sh
```

확인:

```bash
curl http://127.0.0.1:8000/api/v1/health
curl http://192.168.0.10:8000/api/v1/health
```

브라우저는 Raspberry Pi가 제공하는 다음 주소를 사용한다.

```text
https://doubleclick.lab.cbnu.ac.kr/rescue/host/
```

이 모드에서는 UWB 상태만 offline/disconnected이며 구조도 등록, 임무 준비와 로컬 저장 기능을 확인할 수 있다.

로컬 Flutter 개발이 필요할 때만 별도 터미널에서:

```bash
./src/host/scripts/run_host_flutter_web.sh
```

## 7. 실제 UWB 통신

터미널 1:

```bash
cd ~/AI_Rescue_Box
./src/host/scripts/run_uwb_bridge.sh /dev/ttyACM0
```

터미널 2:

```bash
cd ~/AI_Rescue_Box
./src/host/scripts/run_host_api_real.sh
```

상태 확인:

```bash
ros2 topic echo --once /uwb/status
ros2 action list | grep /uwb/send_artifact
ros2 service list | grep /uwb/
curl http://127.0.0.1:8000/api/v1/status
```

## 문제 해결

포트 확인:

```bash
python3 -m serial.tools.list_ports -v
lsof /dev/ttyACM0
```

`Permission denied`이면 `dialout` 설정 후 재로그인한다. `Resource busy`이면 PlatformIO Serial Monitor, 기존 UWB 프로그램 또는 다른 Bridge를 종료한다.

Raspberry Pi에서 `192.168.0.10:8000`이 `Connection refused`이면 Host FastAPI가 실행 중인지, `--host 0.0.0.0`으로 bind되었는지 확인한다.

## 안전 경계

- 같은 Serial port는 Bridge 한 프로세스만 소유한다.
- Host/Jetson ROS graph를 LAN에 노출할 때는 서로 다른 `ROS_DOMAIN_ID`를 사용한다.
- 공개 FastAPI port를 인터넷에 직접 port-forwarding하지 않는다.
- Mock/self-test는 실제 ESP32+DWM1000 무선 성공을 의미하지 않는다.
- 실제 현장 전 1~3 m LOS 환경에서 양방향 전송과 application ACK까지 확인한다.
