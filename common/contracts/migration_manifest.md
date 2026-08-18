# rescue_app Migration Manifest

| 이전 위치 | 단일 Source of Truth 위치 | 책임 |
|---|---|---|
| `rescue_app/host_app/host_app` | `src/host/host_app/host_app` | Host backend |
| `rescue_app/host_app/flutter_app` | `src/host/flutter_app` | Host UI |
| `rescue_app/uwb/flutter_shared` | `common/flutter_shared` | Flutter 공통 모델/API client |
| `rescue_app/uwb/common/ai_rescue_uwb_common` | `src/uwb/common/ai_rescue_uwb_common` | Artifact protocol/transport |
| `rescue_app/uwb/ros2_ws/src/uwb_host_bridge` | `src/host/ros2_ws/src/uwb_host_bridge` | Host serial owner |
| `rescue_app/uwb/ros2_ws/src/uwb_jetson_bridge` | `src/uwb/ros2_ws/src/uwb_jetson_bridge` | Jetson serial owner |
| `rescue_app/jetson_app/jetson_app/mission/coordinator.py` | `src/uwb/runtime/ai_rescue_uwb_runtime/mission_receiver.py` | 수신 조립과 Application ACK |
| `rescue_app/jetson_app/jetson_app/ros_client/uwb.py` | `src/uwb/runtime/ai_rescue_uwb_runtime/ros_client.py` | Jetson UWB ROS adapter |
| `rescue_app/jetson_app/jetson_app/storage/spool.py` | `src/uwb/runtime/ai_rescue_uwb_runtime/spool.py` | 전송 spool |
| `rescue_app/jetson_app/jetson_app/result_service.py` | `src/uwb/runtime/ai_rescue_uwb_runtime/result_sender.py` | Semantic result 제출 |
| Jetson sensor/analysis/risk/planning/API | `src/d_slam/jetson_app` | Jetson 현장 분석 |

이관 후 `prepare_from_rescue_app.sh`를 실행 경로에서 제거하고 두 저장소에 같은 런타임 코드를 병행 유지하지 않는다.
