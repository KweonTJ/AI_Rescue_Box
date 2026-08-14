# AI Rescue Box Jetson Flutter + UWB Runtime

ROS 2 Humble 기반 AI Rescue Box에서 **Jetson Orin Nano가 실행하는 부분**을 준비·빌드·실행하는 패키지다. Jetson Flutter Web, Jetson FastAPI, 공통 UWB artifact protocol, ROS 2 interface와 `uwb_jetson_bridge`를 관리한다.

```text
Jetson Flutter Web
        ↕ REST / WebSocket
Jetson FastAPI 192.168.0.11:8001
        ↕ local ROS 2
Jetson UWB Bridge
        ↕ USB Serial 460800 baud
ESP32 + DWM1000
        ↕ UWB half-duplex
Host ESP32 + DWM1000 → Host Bridge → Host FastAPI / Flutter
```

Flutter는 Serial이나 ROS 2 port를 직접 열지 않는다. ESP32 USB Serial은 `uwb_jetson_bridge` 한 프로세스만 소유한다. Raspberry Pi가 `https://doubleclick.lab.cbnu.ac.kr/rescue/jetson/`에서 Flutter Web을 제공할 때 Jetson에서는 FastAPI와 실제 UWB 사용 시 Bridge만 실행하면 된다.

## 폴더 구조

```text
AI_Rescue_Box/src/uwb/
├── README.md
├── requirements.txt
├── prepare_from_rescue_app.sh
├── config/
│   └── jetson.env.example
├── scripts/
│   ├── _runtime_env.sh
│   ├── build.sh
│   ├── check.sh
│   ├── run_jetson_api_mock.sh
│   ├── run_jetson_api_real.sh
│   ├── run_jetson_flutter_web.sh
│   ├── run_uwb_bridge.sh
│   └── verify_package.py
├── jetson_app/                       # prepare 실행 후 생성
│   ├── jetson_app/
│   └── flutter_app/
├── flutter_shared/                   # prepare 실행 후 생성
├── common/ai_rescue_uwb_common/      # prepare 실행 후 생성
└── ros2_ws/src/                      # prepare 실행 후 생성
    ├── ai_rescue_uwb_common/
    ├── uwb_interfaces/
    └── uwb_jetson_bridge/
```

Host 앱·Host Bridge·ESP32 firmware·테스트·Flutter의 불필요한 플랫폼 scaffold와 build 결과는 포함하지 않는다. Astra, RTAB-Map과 ONNX model 자체는 다른 package에서 관리한다.

## 1. 저장소와 실행 소스 준비

```bash
cd ~
git clone git@github.com:Jeong-Yun-Kim/AI_Rescue_Box.git
cd ~/AI_Rescue_Box
```

이미 받은 저장소:

```bash
cd ~/AI_Rescue_Box
git switch main
git pull --ff-only origin main
```

`rescue_app`이 없다면 한 번 받는다.

```bash
cd ~
git clone git@github.com:Jeong-Yun-Kim/rescue_app.git
```

Jetson 실행 소스를 선별 복사한다.

```bash
cd ~/AI_Rescue_Box/src/uwb
./prepare_from_rescue_app.sh ~/rescue_app
python3 scripts/verify_package.py
```

`rescue_app`이 갱신되면 `git pull` 후 prepare를 다시 실행한다.

## 2. 환경 준비

Ubuntu 22.04와 ROS 2 Humble이 설치되어 있다는 전제다.

```bash
sudo apt update
sudo apt install -y \
  python3-venv python3-pip python3-rosdep \
  python3-colcon-common-extensions python3-opencv python3-numpy rsync
```

처음 한 번만:

```bash
sudo rosdep init
rosdep update
sudo usermod -aG dialout "$USER"
```

`dialout` 적용 후 로그아웃하고 다시 로그인한다.

## 3. 환경 설정

```bash
cd ~/AI_Rescue_Box/src/uwb
cp config/jetson.env.example config/jetson.env
nano config/jetson.env
```

기본값:

| 항목 | 값 |
| --- | --- |
| Jetson IP | `192.168.0.11` |
| FastAPI | `0.0.0.0:8001` |
| 로컬 Flutter Web | `0.0.0.0:8081` |
| 공개 Flutter | `https://doubleclick.lab.cbnu.ac.kr/rescue/jetson/` |
| UWB Serial | `/dev/ttyACM0` |
| baudrate | `460800` |
| ROS local IPC | `ROS_LOCALHOST_ONLY=1` |

## 4. Python·ROS 2 빌드

```bash
cd ~/AI_Rescue_Box
./src/uwb/scripts/build.sh
./src/uwb/scripts/check.sh
```

`build.sh`는 `.venv_uwb`를 만들고 `ai_rescue_uwb_common`, `uwb_interfaces`, `uwb_jetson_bridge`, `jetson_app`을 빌드한다.

## 5. UWB·ROS 없이 앱/API 확인

```bash
cd ~/AI_Rescue_Box
./src/uwb/scripts/run_jetson_api_mock.sh
```

확인:

```bash
curl http://127.0.0.1:8001/api/v1/health
curl http://192.168.0.11:8001/api/v1/health
```

브라우저:

```text
https://doubleclick.lab.cbnu.ac.kr/rescue/jetson/
```

Jetson에서 Flutter Web을 직접 개발할 때만:

```bash
./src/uwb/scripts/run_jetson_flutter_web.sh
```

## 6. 실제 UWB 통신

터미널 1:

```bash
cd ~/AI_Rescue_Box
./src/uwb/scripts/run_uwb_bridge.sh /dev/ttyACM0
```

터미널 2:

```bash
cd ~/AI_Rescue_Box
./src/uwb/scripts/run_jetson_api_real.sh
```

Real mode는 `jetson_app/config/default.yaml`의 ROS sensor, TF와 SLAM provider도 사용한다. 해당 provider가 아직 준비되지 않았다면 Mock API와 실제 Bridge를 따로 실행해 `/uwb/status`부터 확인한다.

상태 확인:

```bash
ros2 topic echo --once /uwb/status
ros2 topic echo /uwb/received_artifact
ros2 action list | grep /uwb/send_artifact
ros2 service list | grep /uwb/
curl http://127.0.0.1:8001/api/v1/status
```

## UWB 통신 기준

- USB Serial: `460800 baud`
- firmware application payload: `111 bytes`
- artifact data chunk: `66 bytes`
- artifact 기본 상한: `10 MiB`
- half-duplex 전송
- firmware frame ACK, peer stored ACK, application applied ACK를 구분

## 문제 해결

```bash
python3 -m serial.tools.list_ports -v
lsof /dev/ttyACM0
```

`Permission denied`이면 `dialout` 적용 후 재로그인한다. `Resource busy`이면 Serial Monitor나 다른 Bridge를 종료한다. Raspberry Pi에서 `192.168.0.11:8001`이 `Connection refused`이면 Jetson FastAPI가 실행 중이고 `0.0.0.0`에 bind되어 있는지 확인한다.

## 안전 경계

- DWM1000은 3.3 V를 사용하고 양쪽 firmware/UWB mode를 동일하게 맞춘다.
- Serial Monitor와 Bridge를 동시에 열지 않는다.
- Host/Jetson ROS graph를 LAN에 노출할 때는 서로 다른 `ROS_DOMAIN_ID`를 사용한다.
- Mock/self-test는 실제 UWB 성공을 의미하지 않는다.
- 실제 센서 topic과 TF는 `jetson_app/config/default.yaml`에서 확인한다.
