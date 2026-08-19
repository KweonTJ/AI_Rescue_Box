# AI Rescue Box

AI Rescue Box는 사고 전 구조도와 재난 후 RGB-D SLAM 지도를 함께 활용해 구조 판단에 필요한 공간정보를 생성하고 제한된 UWB 링크로 전달하는 재난 대응 프로젝트다.

## Source of Truth

`app` 브랜치 하나가 Host, UWB 통신, Jetson SLAM/분석/UI 소스의 단일 Source of Truth다. Stage 0·1에서는 계약 정리와 기존 소스의 책임별 재배치만 수행하며 실제 Mission 적용 흐름은 다음 단계에서 연결한다.

## Source layout

```text
src/
├── host/    # Host backend, Flutter, Host UWB bridge, review/approval
├── uwb/     # protocol, runtime wrappers, schemas/ROS interfaces, firmware
└── d_slam/  # Astra, SLAM, Jetson sensor/analysis backend and Flutter
```

`src` 직하위의 기능 책임은 위 세 디렉터리뿐이다. 통신 계약의 Single Source of Truth는 `src/uwb/interfaces`다.

## Boundary rules

- Host는 d_slam 구현을 직접 import하지 않는다.
- d_slam은 UWB protocol/runtime 구현을 직접 import하지 않는다.
- UWB는 d_slam의 Sensor/SLAM/YOLO 구현을 import하지 않는다.
- 패키지 간 연결은 JSON Schema, ROS Interface 또는 명시된 Port를 사용한다.
- AI 보완 코드는 별도 공통 패키지가 아니라 각 책임 패키지의 실제 기능 안에 둔다.

## Stage 0 contract

- 좌표계: `image_px`, `mission_map`, `slam_map`, camera optical frame
- 변환: `T_mission_map_from_slam_map`
- 버전: `mission_version`, `slam_map_version`, `result_version`, `approved_plan_version`, `artifact_version`
- ACK 단계: `firmware_frame_ack`, `peer_stored_ack`, `application_applied_ack`

자세한 계약은 `src/uwb/interfaces`를 참고한다.

## Verification

```bash
python3 -m compileall -q src
find src -type f -name '*.sh' -print0 | xargs -0 -r -n1 bash -n
python3 scripts/check_repository_structure.py
python3 scripts/check_import_boundaries.py
```

Host, UWB, d_slam의 Unit/Mock과 각 Flutter 앱의 analyze/test는 책임 디렉터리에서 별도로 실행한다.
