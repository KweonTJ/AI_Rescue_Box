# AI Rescue Box 개발 순서

## Stage 0 — 계약 및 Source of Truth 정리

목표:

- `app`을 최종 단일 Source of Truth로 만든다.
- 기능 책임을 `src/host`, `src/uwb`, `src/d_slam`으로 고정한다.
- 통신 계약의 단일 위치를 `src/uwb/interfaces`로 고정한다.
- JSON Schema, Python Validator, ROS Interface의 필수 필드·좌표계·버전 규칙을 일치시킨다.
- 별도 공통 source package를 제거한다.

## Stage 1 — 기능 변경 없는 Source Relocation

목표:

- Host backend/UI/Host UWB bridge를 `src/host`에 둔다.
- protocol/runtime/interfaces/Jetson UWB bridge/firmware를 `src/uwb`에 둔다.
- Astra/SLAM/센서/분석/계획/Jetson API/UI를 `src/d_slam`에 둔다.
- 각 Flutter 앱이 독립 프로젝트 구조를 갖도록 한다.
- 기존 unit/mock test를 책임별 test 디렉터리로 이관한다.
- 외부 저장소의 runtime/build 의존 없이 검증 가능하게 만든다.

Stage 0·1은 구조 검사, legacy 문자열 검사, compileall, shell syntax, import boundary, 패키지별 unit/mock, 가능한 Flutter/ROS 검증이 모두 끝난 뒤에만 완료로 표시한다.

## Stage 2 이후

Stage 0·1 완료 전에는 실제 Host → UWB → d_slam Mission 적용, 실센서 기능 변경, 정합/Change Map/Traversability/Safe Zone/Route AI, 실제 Semantic Result 왕복, systemd/udev/VNC/배포 자동화를 구현하지 않는다.
