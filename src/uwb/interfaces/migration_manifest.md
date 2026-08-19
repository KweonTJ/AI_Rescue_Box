# Stage 0-1 Migration Manifest

이 문서는 Stage 0 계약 정리와 Stage 1 책임별 소스 이관의 최종 위치만 기록한다.

## Communication contracts

- JSON Schema, Python 계약, 좌표계/version 규칙: `src/uwb/interfaces/`
- ROS Interface: `src/uwb/interfaces/ros2/`
- Artifact protocol 구현: `src/uwb/protocol/`
- 통신 runtime, spool, ACK/NACK, sender wrapper와 priority placeholder: `src/uwb/runtime/`
- ROS bridge workspace: `src/uwb/ros2_ws/`
- ESP32/DWM1000 firmware: `src/uwb/firmware/`

## Flutter ownership

별도 Dart shared package를 두지 않는다. Host Flutter에 필요한 API client는 `src/host/flutter_app` 내부에, Jetson Flutter에 필요한 API client는 `src/d_slam/flutter_app` 내부에 각각 포함한다.

## AI placeholder ownership

- map alignment 관련 placeholder: d_slam alignment 기능 내부
- UWB priority/reduction placeholder: UWB runtime 내부
- Host reconstruction 관련 placeholder: Host 기능 내부

Stage 0·1의 최종 HEAD는 외부 소스 준비 단계 없이 이 저장소 자체만으로 Source of Truth를 구성한다.
