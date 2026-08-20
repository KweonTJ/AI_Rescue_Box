# Stage 5B Hardware Validation Runbook

> **상태:** Stage 5A는 Source/배포/설정/결정적 테스트 준비 단계다. 이 문서는 실제 Windows Host, Jetson Orin Nano, Galaxy Tab, Astra, ESP32+DWM1000을 확보한 뒤 수행할 Stage 5B 절차다. Loopback, Serial unit test, PlatformIO compile은 아래 실제 장치 결과를 대체하지 않는다.

## 0. 시험 원칙

- 양쪽 저장소는 같은 `app` commit을 사용한다. 각 장비에서 `git rev-parse HEAD`를 기록한다.
- 처음에는 인터넷 연결을 유지해 설치/build를 끝내고, 마지막 Phase 8에서 인터넷을 완전히 끈다.
- 실제 COM/tty path, VID/PID, DWM1000 pin/radio 값은 장비에서 확인한다. 문서 예시를 사실로 간주하지 않는다.
- 실패 시 재시작 전에 Host `data/logs/`, Jetson `data/logs/jetson/`, UWB spool을 보존한다.
- RGB/Depth frame 원본을 로그로 무제한 저장하지 않는다.
- 모든 수치는 `docs/stage5_measurement_template.md`의 빈 표에 기록한다.

## 1. 시험 전 machine config

| 항목 | Windows | Jetson/Tablet | 확인 방법 |
|---|---|---|---|
| Source SHA | `git rev-parse HEAD` | 동일 | SHA 일치 |
| Host Serial | `AI_RESCUE_UWB_SERIAL_PORT` | — | Device Manager/pyserial |
| Jetson Serial | — | `AI_RESCUE_UWB_SERIAL_PORT` | `python3 -m serial.tools.list_ports -v` |
| Baud | `AI_RESCUE_UWB_BAUD` | 동일 | firmware `monitor_speed`와 일치 |
| YOLO model | — | `AI_RESCUE_YOLO_MODEL` | file 존재, model input 확인 |
| Astra topics | — | d_slam env | `ros2 topic list` |
| RTAB topics/TF | — | d_slam env | `ros2 topic list`, `tf2_echo` |
| Jetson URL | — | APK dart-define | health endpoint 접근 |
| Hotspot | — | SSID/password/interface/address | `hotspot.sh plan/status` |
| Stage 4 tuning | — | selected YAML | commit과 별도 기록 |

## Phase 1 — 설치와 release 준비

### Windows Host

```powershell
git clone <repository-url> AI_Rescue_Box
cd AI_Rescue_Box
git switch app
git pull --ff-only origin app

.\deploy\host_windows\install.ps1
Copy-Item .\src\host\config\host.env.example .\src\host\config\host.env
# host.env에 실제 COM port를 기록
.\deploy\host_windows\build_web.ps1
.\deploy\host_windows\start.ps1 -NoBrowser
.\deploy\host_windows\status.ps1
```

통과 조건:

- Host process/API/Web가 `RUNNING/READY/BUILT`다.
- ESP32를 아직 연결하지 않았다면 Host UWB가 `serial_disconnected`인 것이 정상이다.
- UWB가 없어도 Mission 작성, Prior Map 준비, 이전 결과 조회가 동작한다.

### Jetson

```bash
git clone <repository-url> ~/AI_Rescue_Box
cd ~/AI_Rescue_Box
git switch app
git pull --ff-only origin app

source /opt/ros/<ROS_DISTRO>/setup.bash
./deploy/jetson/install.sh
cp src/d_slam/config/jetson.env.example src/d_slam/config/jetson.env
cp src/uwb/config/jetson.env.example src/uwb/config/jetson.env
# model/topic/serial/network 값을 실제 장치 기준으로 편집
./deploy/jetson/start.sh
./deploy/jetson/status.sh
```

통과 조건:

- install script가 Python/ROS/RTAB/build 상태를 구분해서 출력한다.
- API와 필요한 process PID가 살아 있다.
- 장치를 연결하지 않은 항목은 `WAITING` 또는 `DISCONNECTED`로 표시된다.

### Galaxy Tab APK

Debug 설치용:

```bash
./deploy/tablet_android/build_apk.sh --debug \
  --api-url http://<JETSON_IP>:8001
adb install -r dist/tablet/ai-rescue-box-tablet-debug.apk
```

Release는 private keystore를 저장소 밖에 준비하고 `key.properties.example` 절차를 따른다.

통과 조건:

- APK SHA를 기록한다.
- 실제 Tab에 설치/실행된다.
- 이 시점에 API 연결 실패가 있으면 Phase 2 network를 먼저 해결한다.

## Phase 2 — 개별 장치/서비스 검증

### Host API/Web

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
Invoke-RestMethod http://127.0.0.1:8000/api/v1/status
```

브라우저에서 Host UI를 열어 Mission과 Prior Map을 로컬로 생성한다.

### Jetson API

Jetson 내부:

```bash
curl -fsS http://127.0.0.1:8001/api/v1/health
curl -fsS http://127.0.0.1:8001/api/v1/status
```

다른 장치:

```text
http://<JETSON_IP>:8001/api/v1/health
```

### Tablet → Jetson

- Tablet에서 health/status, Mission list/current, current map/result 화면을 연다.
- HTTP status와 앱 error 메시지를 기록한다.

### Astra RGB-D

```bash
ros2 topic list | grep camera
ros2 topic hz /camera/color/image_raw
ros2 topic hz /camera/depth/image_raw
ros2 topic echo --once /camera/color/camera_info
```

확인:

- color/depth/camera_info topic이 설정과 일치한다.
- timestamp와 frame_id가 유효하다.
- frame rate는 측정표에 기록한다.

### RTAB-Map / TF

```bash
ros2 topic hz /rtabmap/odom
ros2 topic hz /rtabmap/map
ros2 topic echo --once /rtabmap/info
ros2 run tf2_ros tf2_echo map odom
```

확인:

- tracking이 유지되는 구간과 loss 구간을 구분한다.
- map/odom frame이 config와 일치한다.

### YOLO model

```bash
./deploy/jetson/status.sh
curl -fsS http://127.0.0.1:8001/api/v1/status
```

실제 분석을 한 번 실행해 model load, inference status와 오류를 기록한다. `CONFIGURED` 표시는 file 경로 존재만 뜻하며 inference 성공을 뜻하지 않는다.

## Phase 3 — ESP32 Serial 및 기본 UWB

### 3.1 두 ESP32 role firmware build/flash

```bash
cd src/uwb/firmware
pio run -e host_node
pio run -e jetson_node
```

compile 성공 후 실제 확인한 port로만 flash한다.

```bash
pio run -e host_node -t upload --upload-port <HOST_ESP32_PORT>
pio run -e jetson_node -t upload --upload-port <JETSON_ESP32_PORT>
```

기록:

- firmware source SHA
- PlatformIO environment
- 실제 board/ESP32 USB identifier
- 실제 DWM1000 wiring과 radio 설정
- flash 성공/실패

### 3.2 USB detection/Serial open

Windows:

```powershell
.\.venv-host\Scripts\python.exe -m serial.tools.list_ports -v
.\deploy\host_windows\stop.ps1
# host.env의 실제 COM을 수정
.\deploy\host_windows\start.ps1 -NoBrowser
.\deploy\host_windows\status.ps1
```

Jetson:

```bash
python3 -m serial.tools.list_ports -v
ls -l /dev/ttyACM* /dev/ttyUSB* 2>/dev/null
# jetson.env의 실제 device를 수정한 뒤
./deploy/jetson/stop.sh
./deploy/jetson/start.sh
./deploy/jetson/status.sh
```

통과 조건:

- 양쪽 Serial이 `CONNECTED`다.
- USB를 한 번 분리/재연결했을 때 API 전체가 죽지 않고 bounded reconnect 후 복구한다.
- disconnect/reconnect 횟수와 시간을 기록한다.

### 3.3 HELLO/basic transfer

실제 Firmware Serial framing과 Radio 경계를 확인하는 최소 artifact를 전송한다. 기존 protocol CLI/진단 기능을 사용하고 새 packet 형식을 만들지 않는다.

확인:

- firmware frame ACK
- peer stored ACK
- SHA 일치
- retry 횟수
- application ACK를 요구하지 않는 basic 저장 전송과 요구하는 전송을 구분

## Phase 4 — Host Mission → Jetson

1. Host UI에서 Prior Map과 Mission Manifest를 준비한다.
2. 전송 직전 file size와 SHA-256을 기록한다.
3. Host에서 Mission 전송을 시작한다.
4. Jetson `data/uwb_spool/jetson/completed/`와 Stage 2 log를 관찰한다.
5. `/d_slam/load_mission` 결과와 `application_applied_ack`를 확인한다.

통과 조건:

- base map: frame ACK + peer stored ACK
- mission manifest: frame ACK + peer stored ACK + application applied ACK
- Jetson Mission state가 READY다.
- mission_id/version/base-map version이 양쪽에서 일치한다.
- 실패 시 NACK/error code가 Host에 보이고 Host API는 계속 동작한다.

## Phase 5 — Astra → RTAB → YOLO+Depth → Stage 4 Analysis

1. 실제 로봇/카메라를 안전한 시험 공간에서 움직인다.
2. Astra color/depth, RTAB odometry/map/status를 확인한다.
3. Tablet 또는 API에서 분석을 실행한다.
4. 다음 산출물을 확인한다.
   - real survivor detection과 Depth 기반 3D 위치
   - risk objects/regions
   - Prior↔Live bounded SE(2) alignment status/confidence
   - change/traversability map
   - multi-route 평가
   - safe zones
   - semantic result 및 semantic rescue map preview
5. 각 component time과 전체 analysis time을 기록한다.

실패 분류:

- SENSOR_UNAVAILABLE
- RTAB tracking/map unavailable
- TF/frame mismatch
- model load/inference error
- depth association error
- alignment rejected/low confidence
- route/safe-zone generation failure

Stage 4 threshold/search 범위 변경 시 사용한 YAML 파일과 diff를 반드시 기록한다.

## Phase 6 — Jetson Result/Preview → Host

1. Jetson current semantic result와 preview file size/SHA를 기록한다.
2. `/api/v1/results/current/send` 또는 Tablet의 기존 send flow를 실행한다.
3. Host 수신 spool, Host API status, UI map/result 반영을 확인한다.
4. peer stored ACK와 Host application applied ACK latency를 기록한다.

통과 조건:

- semantic_result JSON의 mission/result/base-map version이 Host current mission과 일치한다.
- map_preview PNG metadata가 일치한다.
- Host에 Semantic Rescue Map과 route/victim/risk가 표시된다.
- 결과/preview 순서가 달라도 contract 검증과 ACK가 안정적이다.

## Phase 7 — Approved Plan → Jetson

1. Host에서 result를 검토하고 Approved Plan을 만든다.
2. plan version/file size/SHA를 기록한다.
3. UWB로 전송한다.
4. Jetson `/d_slam/apply_approved_plan` 결과와 application ACK를 확인한다.

통과 조건:

- approved_plan mission/version이 current Mission과 일치한다.
- Jetson current approved plan이 갱신된다.
- 잘못된 version/mission은 명확히 거절되고 기존 state는 보존된다.

## Phase 8 — 완전 Offline 반복

1. Windows/Jetson/Tablet의 인터넷 uplink를 끈다.
2. 필요하다면 Jetson Hotspot만 유지한다.
3. DNS/cloud/external domain 접근이 없는지 확인한다.
4. Phase 4–7을 다시 수행한다.

통과 조건:

- `doubleclick.lab.cbnu.ac.kr`, Raspberry Pi, 외부 FastAPI/cloud API 없이 전체 흐름이 반복된다.
- Host Web, Jetson API, Tablet, UWB transfer가 local-only로 동작한다.
- 실제 offline 성공 여부와 반복 횟수를 측정표에 기록한다.

## 9. 종료 및 증거 보존

```powershell
.\deploy\host_windows\status.ps1
.\deploy\host_windows\stop.ps1
```

```bash
./deploy/jetson/status.sh
./deploy/jetson/stop.sh
```

보존:

- 양쪽 Source SHA와 config checksum
- PlatformIO build/flash log
- Host/Jetson process log
- UWB transfer id, SHA/ACK/retry 기록
- API response/분석 result metadata
- 측정표

비밀정보는 제거한다. Hotspot password, Android signing password/keystore는 첨부하거나 commit하지 않는다.
