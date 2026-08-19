# AI Rescue Box

AI Rescue Box는 사고 전 구조도와 재난 후 RGB-D SLAM 지도를 비교해 구조에 필요한 의미 정보를 생성하고 제한된 UWB 링크로 Host에 전달하는 재난 공간정보 모듈이다.

## Source of Truth

`app` 브랜치가 Host, UWB 통신, Jetson 센서·SLAM·분석 소스의 단일 Source of Truth가 되는 것을 목표로 한다. 현재 Stage 0 계약 정리와 Stage 1 Source Relocation을 진행 중이며, 완료 여부는 `scripts/check_repository_structure.py`와 패키지별 검증 결과로 판단한다.

## 책임 경계

```text
AI_Rescue_Box/
├── src/
│   ├── host/      # Host FastAPI, Flutter, Host UWB bridge, 검토·승인
│   ├── uwb/       # protocol/runtime/interfaces/ROS bridge/firmware
│   └── d_slam/    # Astra, RTAB-Map, 센서·분석·계획, Jetson API/UI
├── docs/
└── scripts/
```

`src` 직하위 기능 책임은 `host`, `uwb`, `d_slam` 세 개로 제한한다. 별도 공통 소스 패키지는 두지 않는다.

## 계약 위치

통신 계약의 Single Source of Truth는 `src/uwb/interfaces/`다.

- JSON Schema: `src/uwb/interfaces/schemas/`
- Python 계약: `src/uwb/interfaces/python/`
- ROS Interface: `src/uwb/interfaces/ros2_ws/src/ai_rescue_interfaces/`
- 좌표계: `image_px`, `mission_map`, `slam_map`, camera optical frame, `T_mission_map_from_slam_map`
- 독립 버전: mission/slam_map/result/approved_plan/artifact version
- ACK 단계: firmware frame / peer stored / application applied

## 의존 경계

- `d_slam`은 UWB protocol/runtime 구현을 import하지 않는다.
- `uwb`는 Astra, RTAB-Map, YOLO, Depth, Risk, Planning 구현을 소유하지 않는다.
- `host`는 `d_slam` 구현을 직접 import하지 않는다.
- 패키지 간 연결은 interfaces와 명시된 port를 사용한다.

Stage 2의 실제 Mission 적용 연결은 이 단계에서 구현하지 않는다.
