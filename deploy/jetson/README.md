# Jetson Local Server

Jetson Orin Nano는 화면/VNC용 장치가 아니라 현장 연산 + Local API server다.

## Prepare

Jetson에 기존 Astra/RTAB-Map/d_slam 의존성을 준비하고 Jetson API Python package를 설치한다.

```bash
python3 -m pip install -e './src/d_slam/jetson_app[api]'
```

ROS2/CUDA/Astra나 YOLO weight는 repository가 자동 설치/다운로드하지 않는다.

## Stage 3 real analysis

기존 Astra + RTAB-Map launch를 먼저 실행한다.

```bash
ros2 launch d_slam d_slam.launch.py
```

기본 topic은 repository launch와 동일하다.

```text
RGB         /camera/color/image_raw
Depth       /camera/depth/image_raw
CameraInfo  /camera/color/camera_info
RTAB map    /rtabmap/map
RTAB odom   /rtabmap/odom
SLAM frame  map
```

ONNX weight는 Jetson 로컬 경로를 지정한다.

```bash
export AI_RESCUE_ANALYSIS_MODE=real
export AI_RESCUE_YOLO_MODEL=/path/to/person-model.onnx
```

필요하면 `src/d_slam/config/jetson.env.example`의 topic/depth/sync/mission-transform 값을 환경에 맞게 override한다. `real` 모드에서 센서, TF, RTAB-Map 또는 model이 없으면 API는 unavailable/503을 반환하며 Mock으로 자동 전환하지 않는다.

## Start Local API

```bash
./deploy/jetson/start.sh
```

기본값:

```text
AI_RESCUE_JETSON_API_HOST=0.0.0.0
AI_RESCUE_JETSON_API_PORT=8001
AI_RESCUE_DATA_ROOT=<repo>/data/jetson
```

상태 확인:

```bash
curl http://127.0.0.1:8001/api/v1/status
```

현재 Mission에 대해 실제 분석을 실행하면 `semantic_result_vN.json`, `semantic_result.json`, `map_preview.png`, `map_preview.json`이 같은 Mission directory에 저장된다.

```bash
curl -X POST http://127.0.0.1:8001/api/v1/analysis
```

Stage 2의 기존 `/uwb/submit_rescue_update` 반환 경로에는 저장된 최신 결과를 그대로 연결한다.

```bash
PYTHONPATH=src/d_slam/jetson_app \
  python3 -m jetson_app.stage2_submit --use-current
```

이 명령은 UWB protocol/runtime을 새로 만들지 않고 기존 `SubmitRescueUpdate` action을 사용한다. 실제 ESP32+DWM1000 radio 검증은 Stage 5 범위다.

Galaxy Tab에서는 Jetson hotspot/USB Network/같은 LAN의 **Jetson IP**로 같은 API를 조회한다. 외부 인터넷이나 외부 Web server는 Jetson API 실행 조건이 아니다. Hotspot 자동 생성/systemd/udev는 Stage 5 범위다.
