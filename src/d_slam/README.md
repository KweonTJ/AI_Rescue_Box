# d_slam

Jetson sensor, SLAM, AI analysis, Local API와 Galaxy Tab client source를 소유한다.

- `astra_camera/`, `astra_camera_msgs/`: Astra RGB-D source
- `d_slam/`: existing SLAM/nvblox/RTAB-Map integration
- `jetson_app/`: mission storage, sensor adapters, perception, depth fusion, risk, alignment, planning, semantic result and Jetson Local FastAPI
- `flutter_app/`: Galaxy Tab Android APK Source. SLAM/YOLO/Depth/UWB 연산은 APK에서 수행하지 않는다.
- `config/jetson.env.example`: Jetson Local API/data-root 예시

Stage 0·1의 source/책임 경계를 유지한다. Stage 1.5에서는 실행 플랫폼과 외부 서버 의존만 분리하며, 수신 Mission을 RTAB-Map에 실제 적용하거나 Host↔UWB↔Jetson E2E를 새로 연결하지 않는다.

## Jetson Local API

기본 bind는 Tablet이 같은 로컬 네트워크에서 접근할 수 있도록 다음과 같다.

```bash
export AI_RESCUE_JETSON_API_HOST=0.0.0.0
export AI_RESCUE_JETSON_API_PORT=8001
export AI_RESCUE_DATA_ROOT="$PWD/data/jetson"
./deploy/jetson/start.sh
```

실제 장치에서는 방화벽/네트워크 정책으로 필요한 로컬 인터페이스만 노출한다. 외부 인터넷이나 별도 Raspberry Pi/Web server는 API 실행 조건이 아니다.

## Galaxy Tab APK

기본 개발/대회 연결은 Jetson hotspot gateway `192.168.50.1:8001`이다. 다른 사설 LAN/USB Network 주소는 build-time define 하나로 변경한다.

```bash
JETSON_API_BASE_URL=http://192.168.50.1:8001 \
  ./deploy/tablet_android/build_apk.sh
```

APK는 REST/WebSocket client일 뿐이며 Jetson의 실제 연산 코드를 포함하지 않는다. 기존 Linux/VNC 사용은 개발·디버그 선택 사항이다.
