# Jetson Local Server

Jetson Orin Nano는 화면/VNC용 장치가 아니라 현장 연산 + Local API server다.

## Prepare

Jetson에 기존 Astra/RTAB-Map/d_slam 의존성을 준비하고 Jetson API Python package를 설치한다.

```bash
python3 -m pip install -e './src/d_slam/jetson_app[api]'
```

Stage 1.5에서는 ROS2/CUDA/Astra를 새로 설치하거나 자동 구성하지 않는다.

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

Jetson 자체 확인:

```bash
curl http://127.0.0.1:8001/api/v1/health
```

Galaxy Tab에서는 Jetson hotspot/USB Network/같은 LAN의 **Jetson IP**로 접근한다. 예를 들어 기본 hotspot gateway를 사용할 경우 `http://192.168.50.1:8001`이다.

외부 인터넷, Raspberry Pi, 외부 Web server는 Jetson API 실행 조건이 아니다. Hotspot 자동 생성/systemd/udev는 이 단계 범위가 아니다.
