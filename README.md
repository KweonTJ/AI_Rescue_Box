# AI Rescue Box

AI Rescue Box는 사고 전 구조도와 재난 후 RGB-D SLAM 지도를 비교하여 요구조자, 위험 구역, 통행 가능 영역, 구조 경로와 Safe Zone을 생성하고 제한된 UWB 링크로 Host에 전달하는 플랫폼 독립형 재난 공간정보 모듈이다.

## Source of Truth

`app` 브랜치가 Host 앱, Jetson 앱, UWB 통신, SLAM 및 공통 계약을 함께 관리하는 단일 Source of Truth다. `Jeong-Yun-Kim/rescue_app`을 실행 시점에 복사하는 구조는 제거하며, 모든 수정은 이 저장소에서 수행한다.

## 책임 경계

```text
AI_Rescue_Box/
├── src/
│   ├── host/      # Host FastAPI, Flutter, Host UWB bridge, 검토·승인
│   ├── uwb/       # Jetson 통신, protocol, spool, ACK/NACK, 전송 wrapper
│   └── d_slam/    # Astra, RTAB-Map, YOLO+Depth, risk, planning, Jetson UI/API
├── common/
│   ├── contracts/ # JSON/ROS/Python 계약, 좌표계와 버전 규칙
│   ├── ai_boost/  # 패키지별 재사용 AI 전략 인터페이스
│   └── flutter_shared/
├── deploy/
└── scripts/
```

의존 방향은 `host -> contracts + uwb`, `uwb -> contracts + d_slam application interface`, `d_slam core -> contracts`로 유지한다. 실제 조립은 Jetson API composition root에서만 수행한다. Serial port는 UWB bridge 한 프로세스만 연다.

## 좌표계

- `image_px`: 원본 구조도 픽셀 좌표
- `mission_map`: Host 구조도를 축척 적용한 meter 좌표이며 외부 계약의 표준 좌표계
- `slam_map`: RTAB-Map이 생성한 ROS `map` 좌표
- `T_mission_map_from_slam_map`: SLAM 결과를 Mission 좌표로 변환하는 2D rigid transform

자세한 규칙은 `common/contracts/coordinates.md`를 참고한다.

## 개발 순서

현재 브랜치는 단계 0과 단계 1을 합쳐 저장소 구조, 공통 계약과 기존 앱 소스 이관을 먼저 완료한다. 이후 Mission Load, 실센서 E2E, 결과 왕복, AI Boost, 오프라인 배포 순서로 진행한다. 자세한 완료 기준은 `docs/DEVELOPMENT_ORDER.md`에 있다.

## 정적 검증

```bash
python3 scripts/check_repository_structure.py
python3 -m compileall -q common src/host/host_app src/uwb/runtime src/d_slam/jetson_app
find src scripts -type f -name '*.sh' -print0 | xargs -0 -n1 bash -n
```

실장 검증은 별도로 구분한다.

- Unit/Mock: ROS, Astra, DWM1000 없이 실행
- Integration: 로컬 ROS graph와 Mock transport
- Hardware: Astra + RTAB-Map + ESP32/DWM1000 양방향 Application ACK
