# Host

Windows 지휘소에서 실행하는 Host 책임 소스다.

## Ownership

- `host_app/`: 수신 Mission 저장, semantic reconstruction, human review, Approved Plan, FastAPI/WebSocket
- `flutter_app/`: Chrome/Edge용 Flutter Web Rescue Map / briefing UI
- `ros2_ws/src/uwb_host_bridge/`: Host UWB ROS bridge source
- `config/`, `scripts/`, `tests/`: 로컬 설정·실행·검증

통신 계약은 `../uwb/interfaces/`가 Single Source of Truth다. Host는 d_slam 내부 구현을 직접 import하지 않는다.

## 정상 제품 흐름

정상 제품에서는 **Tablet → Jetson → UWB → Host** 순서로 Mission과 Rescue Map이 들어온다. Host는 `base_map`과 `mission_manifest`를 수신하면 ID/Version/SHA를 검증해 자동 등록하며, 동일 Version/동일 내용의 재수신은 idempotent duplicate로 처리한다. 같은 Version이 다른 내용으로 재사용되면 NACK한다.

기존 Host의 구조도 등록 및 Host → Jetson Mission 전송 기능은 개발·복구·백업용으로 삭제하지 않고 유지한다.

## Semantic Rescue Map

Host는 full SLAM map snapshot을 주기적으로 받아야 하는 구조가 아니다.

- 최초 `semantic_result`를 Jetson source semantic state로 저장한다.
- 이후 `map_delta`의 `base_result_version/result_version` 연속성을 검증한다.
- stale/duplicate artifact는 idempotent하게 처리하고 version gap은 잘못 적용하지 않고 NACK/recovery 대상으로 남긴다.
- raw received artifact와 derived reconstruction state를 분리한다.
- 기존 `ReviewSession`의 operator edit overlay와 Undo/Redo/Approved Plan은 source semantic state와 분리한다.
- `entry_routes`와 `return_routes`를 서로 다른 레이어로 표시하고 둘 다 승인·제외·경로 point 수정 대상으로 다룬다.
- Approved Plan은 호환용 `approved_routes`와 함께 `approved_entry_routes`, `approved_return_routes`를 기록한다.
- WebSocket 경로를 통해 최신 semantic state가 UI에 반영된다.

## Mission / Approved Plan

Tablet Mission을 Host가 UWB로 수신할 때 `MissionStore`의 기존 immutable version/SHA 검증을 재사용한다. Jetson의 Mission 상태는 **STORED**와 **ACTIVE**가 분리되며, `mission_state`를 통해 ACTIVE 상태가 Host에 동기화된다.

사람이 최신 Rescue Map에서 요구조자, 위험구역, 진입·복귀 경로, Safe Zone, 구조팀 배치를 검토·수정한 뒤 기존 Approved Plan 흐름으로 Jetson에 재전송한다.

## Windows product path

최초 1회:

```powershell
.\deploy\host_windows\setup.ps1
```

이후:

```powershell
.\deploy\host_windows\start.ps1
```

기존 `setup.ps1`의 Python 3.10+ 검사, Flutter 검사, `host.env.example → host.env` 최초 생성, 기존 env 보존, runtime directory/sanity check, serial blind auto-selection 금지 특성을 유지한다. ESP32/UWB가 연결되지 않아도 setup 자체는 가능하다.

상세 Windows lifecycle은 `deploy/host_windows/README.md`를 따른다.

## Verify

최종 integration에서는 변경 기능의 targeted pytest와 `flutter analyze`를 우선한다. 실제 Windows COM/UWB radio 검증은 hardware validation 범위다.
