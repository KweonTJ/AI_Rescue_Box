# Host

Host PC / 지휘소 책임 소스다.

## Ownership

- `host_app/`: FastAPI, 구조도 등록·검증·정규화, Mission/Store, Semantic Result/Map Preview 수신과 검토, Approved Plan 생성
- `flutter_app/`: 독립 Host Flutter 앱
- `ros2_ws/src/uwb_host_bridge/`: Host 측 UWB ROS bridge
- `config/`: Host 설정
- `scripts/`: Host build/run/check
- `tests/`: Host Unit/Mock

통신 계약은 `../uwb/interfaces`가 Single Source of Truth다. Host는 d_slam 구현을 직접 import하지 않는다.

## Verify

```bash
./scripts/check.sh
```

Host Flutter는 `flutter_app`에서 `flutter analyze`와 `flutter test`로 검증한다. ROS 2 Humble 환경이 source되어 있으면 `ros2_ws`에서 `colcon build`를 수행한다.
