# Galaxy Tab Android APK

Source는 `src/d_slam/flutter_app`이며 기본 Jetson API URL은 `http://192.168.50.1:8001`이다. URL은 Flutter build-time define으로 변경되므로 Hotspot, USB network, 같은 LAN을 모두 지원한다.

## Debug APK

```bash
./deploy/tablet_android/build_apk.sh --debug \
  --api-url http://192.168.50.1:8001
```

산출물:

- `dist/tablet/ai-rescue-box-tablet-debug.apk`
- 동일 파일의 `.sha256`

## Signed Release APK

개인 keystore를 저장소 **밖**에 준비한다. Stage 5A에서는 key를 만들거나 commit하지 않는다.

```bash
cp src/d_slam/flutter_app/android/key.properties.example \
   src/d_slam/flutter_app/android/key.properties
```

실제 `storeFile`, alias, password를 로컬 `key.properties`에 기록한 뒤 실행한다.

```bash
./deploy/tablet_android/build_apk.sh --release \
  --api-url http://192.168.50.1:8001
```

산출물은 `dist/tablet/ai-rescue-box-tablet-release.apk`다. `key.properties`, `*.jks`, `*.keystore`는 Git에 넣지 않는다.

WebSocket endpoint가 API URL과 다른 환경에서만 `--ws-url`을 추가한다. 보통 앱은 API URL을 기준으로 연결하므로 생략한다.

## Stage 5B 설치

USB debugging을 사용하는 경우:

```bash
adb devices
adb install -r dist/tablet/ai-rescue-box-tablet-debug.apk
# 또는 서명된 release APK
```

직접 설치 시 APK를 Galaxy Tab으로 옮겨 설치한다. Android에서 unknown-app install 허용 범위는 설치 후 다시 제한한다.

설치 후 검증 순서:

1. Tablet와 Jetson을 Hotspot/USB network/LAN 중 하나로 연결
2. 브라우저에서 `http://<JETSON_IP>:8001/api/v1/health` 확인
3. 앱 실행 후 Mission/Map/Result 조회
4. 인터넷을 끈 상태에서 반복

Stage 5A에서는 APK build source/signing flow만 준비하며 실제 Galaxy Tab 설치와 Tablet↔Jetson 연결은 검증하지 않는다.
