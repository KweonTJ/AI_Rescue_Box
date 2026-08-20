# Host

Windows 지휘소에서 실행하는 Host 책임 소스다.

## Ownership

- `host_app/`: 구조도 등록·정규화, Mission, semantic reconstruction, human review, Approved Plan, FastAPI/WebSocket
- `flutter_app/`: Chrome/Edge용 Flutter Web
- `ros2_ws/src/uwb_host_bridge/`: Host UWB ROS bridge source
- `config/`, `scripts/`, `tests/`: 로컬 설정·실행·검증

통신 계약은 `../uwb/interfaces/`가 Single Source of Truth다. Host는 d_slam 내부 구현을 직접 import하지 않는다.

## Semantic Rescue Map

Host는 full SLAM map snapshot을 주기적으로 받아야 하는 구조가 아니다.

- 최초 `semantic_result`를 Jetson source semantic state로 저장한다.
- 이후 `map_delta`의 `base_result_version/result_version` 연속성을 검증한다.
- `host_app.ai_boost(...)` entry point를 거쳐 deterministic reconstruction을 수행한다.
- stale/duplicate artifact는 idempotent하게 처리하고 version gap은 잘못 적용하지 않고 NACK/recovery 대상으로 남긴다.
- raw received artifact는 UWB completed spool에 유지하고 derived state는 `host_reconstruction/`에 별도로 유지한다.
- 기존 `ReviewSession`의 operator edit overlay와 Undo/Redo/Approved Plan은 source semantic state와 분리한다. 새 delta로 source가 갱신되어도 edit overlay를 재적용하고, 대상 entity가 사라지면 conflict event를 발생시킨다.
- 기존 EventHub/WebSocket 경로를 통해 최신 semantic state가 UI에 자동 반영된다.

`host_app.ai_boost()`는 AI model이 없어도 존재하며 `enabled=False`에서 deterministic merge를 그대로 수행한다.

## Mission / Approved Plan

Host는 사고 전 JPEG/PNG를 정규화하고 scale, robot start pose/yaw, entrances, Mission ID/name/version, team/rescuer 수, notes를 Mission Manifest에 결합해 UWB로 보낸다. Jetson의 UWB application ACK는 **저장 완료(STORED)**를 의미하며 Tablet에서 ACTIVE로 선택했다는 뜻이 아니다.

사람이 최신 Rescue Map을 검토·수정한 뒤 기존 Approved Plan 흐름으로 Jetson에 재전송한다.

## Windows product path

최초 1회:

```powershell
.\deploy\host_windows\setup.ps1
```

이후:

```powershell
.\deploy\host_windows\start.ps1
```

기존 `setup.ps1`의 Python 3.10+ 검사, Flutter 검사, `install.ps1`/`build_web.ps1` 호출, `host.env.example → host.env` 최초 생성, 기존 env 보존, runtime directory/sanity check, serial blind auto-selection 금지 특성을 유지한다. ESP32/UWB가 연결되지 않아도 setup 자체는 가능하고 setup 완료 뒤 start에는 Flutter SDK가 필요하지 않다.

상세 Windows lifecycle은 `deploy/host_windows/README.md`를 따른다.

## Verify

```bash
./scripts/check.sh
```

Flutter는 `flutter_app`에서 `flutter analyze`, `flutter test`, `flutter build web`으로 확인한다.
