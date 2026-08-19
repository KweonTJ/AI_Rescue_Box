# UWB Communication Interfaces

`src/uwb/interfaces`는 AI Rescue Box의 Host ↔ Jetson 통신 경계에서 사용하는 계약의 Single Source of Truth다.

- `schemas/`: Mission, Semantic Result, Approved Plan, Map Delta, Urgent Event JSON Schema
- `python/`: dependency-free Python contract/coordinate/version helpers
- `ros2/`: application-level ROS service/action interface
- `coordinates.md`: `image_px`, `mission_map`, `slam_map` 좌표계와 변환 규칙
- `versioning.md`: 독립 version과 ACK 단계 규칙
- `migration_manifest.md`: Stage 0·1 최종 책임 위치

구현 코드는 이 디렉터리에 두지 않는다. Artifact protocol은 `src/uwb/protocol`, 통신 runtime은 `src/uwb/runtime`, Host/Jetson 기능 구현은 각각 자신의 책임 디렉터리가 소유한다.
