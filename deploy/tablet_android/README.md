# Galaxy Tab Android Client

`src/d_slam/flutter_app`은 Stage 1.5부터 **Galaxy Tab용 Android APK Source**다. APK는 UI client이며 SLAM, YOLO, Depth, UWB protocol 연산을 수행하지 않는다.

## Build debug APK

저장소 루트에서:

```bash
./deploy/tablet_android/build_apk.sh
```

기본 Jetson API:

```text
http://192.168.50.1:8001
```

다른 Jetson hotspot/USB Network/사설 LAN 주소를 사용할 때는 한 번만 지정한다.

```bash
JETSON_API_BASE_URL=http://192.168.10.1:8001 \
  ./deploy/tablet_android/build_apk.sh
```

Flutter 내부 설정 키는 `JETSON_API_BASE_URL`이고 WebSocket URL은 같은 base에서 자동 계산한다. 특별히 다른 WebSocket endpoint가 필요한 개발 환경에서만 `JETSON_WS_URL` dart-define을 사용할 수 있다.

Stage 1에서 Android app source는 남아 있었지만 Gradle Wrapper binary가 trim되어 있었다. `build_apk.sh`는 설치된 Flutter SDK와 일치하는 Wrapper/build scaffold만 임시 생성해 보완한 뒤 기존 `android/app`, Manifest, Dart source를 그대로 빌드한다. 별도 `rescue_app` 또는 외부 서버 source는 사용하지 않는다.

Debug APK 출력:

```text
src/d_slam/flutter_app/build/app/outputs/flutter-apk/app-debug.apk
```

Android Manifest에는 `INTERNET` permission과 로컬 Jetson HTTP 접근을 위한 cleartext 허용만 유지하며 custom CA/trust-all 설정은 사용하지 않는다.

## Runtime

1. APK를 Galaxy Tab에 설치한다.
2. Tab을 Jetson hotspot, USB Network 또는 같은 로컬 LAN에 연결한다.
3. 빌드 때 지정한 Jetson API 주소가 해당 Jetson IP/port와 일치하는지 확인한다.
4. 앱을 실행한다.

Jetson이 꺼졌거나 네트워크가 끊기면 기존 controller가 예외를 UI 상태로 보존하며 앱 프로세스를 종료하지 않는다. 상태 화면에서 `Jetson 연결 중 / 연결됨 / 연결 실패`를 확인할 수 있다.

Release signing, Play Store, hotspot 자동 설정은 이 단계 범위가 아니다.
