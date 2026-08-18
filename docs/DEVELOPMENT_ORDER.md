# AI Rescue Box 개발 순서

## 완료된 기반 작업: 단계 0 + 단계 1

- `src/host`, `src/uwb`, `src/d_slam` 책임 경계 고정
- `common/contracts`에 JSON, Python, ROS 계약 정의
- 좌표계와 독립 Version 규칙 정의
- 기존 `rescue_app` 런타임 소스를 이 저장소로 이관
- `prepare_from_rescue_app.sh` 런타임 의존 제거
- Jetson 통신 coordinator, UWB ROS client, spool, result/preview sender를 `src/uwb`로 이동
- 센서, 분석, Mission 저장, Jetson API와 Flutter를 `src/d_slam`으로 이동

## 단계 2: Host → UWB → d_slam Mission 연결

1. Host가 `base_map`과 `mission_manifest`를 순서대로 전송한다.
2. Jetson UWB가 두 Artifact를 SHA-256과 Version으로 검증한다.
3. UWB runtime이 d_slam Mission application interface를 호출한다.
4. d_slam이 구조도와 Manifest를 버전 디렉터리에 원자적으로 저장한다.
5. Mission state를 `READY`로 바꾼 뒤 Application ACK를 반환한다.

완료 기준: Host에서 보낸 동일 Mission과 구조도가 Jetson Flutter/VNC 화면에 표시된다.

## 단계 3: d_slam 실센서 E2E

- Astra RGB, registered Depth, CameraInfo의 크기·Frame ID·Timestamp 검사
- RTAB-Map Occupancy와 TF `map -> camera/base` 연결
- 실제 YOLO ONNX/TensorRT 모델 연결
- Person bbox → median depth → camera XYZ → ROS map → mission_map 변환
- Depth/PointCloud 기반 기본 risk와 A* 경로 생성

완료 기준: Jetson 화면에 Robot, Victim, Risk, Route가 실제 센서 데이터로 표시된다.

## 단계 4: 결과 왕복

- d_slam이 `semantic_result`와 `map_preview`를 생성한다.
- UWB가 전송 Artifact와 Priority를 결정해 Host로 보낸다.
- Host가 스키마, Mission ID, Version과 SHA-256을 검증하고 Overlay한다.
- Host의 `approved_plan`을 Jetson으로 되돌려 d_slam이 적용한다.

## 단계 5 이후

1. Prior/Live map 정합과 Change Map
2. Traversability, 다중 경로, Route Ranker, Safe Zone
3. `urgent_event`, `map_delta`, Snapshot scheduler
4. Host reconstruction과 change summary
5. systemd, udev, Flutter/VNC 자동 실행
6. rosbag 및 실제 UWB 정량 검증
