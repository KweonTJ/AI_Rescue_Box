# UWB

Host ↔ Jetson 통신과 통신 계약만 소유한다.

## Ownership

- `protocol/`: artifact metadata, chunking, SHA-256, ACK/NACK, retry, half-duplex, spool core
- `runtime/`: application-facing artifact sender/receiver ports와 communication wrappers
- `interfaces/`: JSON Schema와 ROS Interface의 Single Source of Truth
- `ros2_ws/`: Jetson-side UWB bridge와 link-level ROS interfaces
- `firmware/`: ESP32 + DWM1000 firmware
- `config/`, `scripts/`, `tests/`: 통신 설정·실행·검증

Astra, RTAB-Map, YOLO/Depth/Risk/Alignment/A*, Jetson 분석 FastAPI, Jetson Flutter는 이 패키지가 소유하지 않는다.

## ACK contract

- `firmware_frame_ack`
- `peer_stored_ack`
- `application_applied_ack`

## Verify

```bash
./scripts/check.sh
```

ROS 2 Humble 환경이 source되어 있으면 `ros2_ws`에서 `colcon build`를 수행한다.
