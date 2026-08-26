# AI Rescue Box

제13회 전국 ICT융합 공모전 제출용 통합 릴리스입니다.

AI Rescue Box는 사고 전 건축도면과 재난 현장의 RGB-D SLAM 정보를 동일 좌표계로 결합하고, 요구조자·장애물·위험구역·진입 경로를 구조용 2D **Rescue Map**으로 제공하는 Local Edge AI 재난 탐사 모듈입니다.

## 제품 구성

- **AI Rescue Box / Jetson Orin Nano**
  - Astra RGB-D 입력
  - RTAB-Map 기반 RGB-D SLAM
  - MediaPipe EfficientDet 기반 요구조자 탐지
  - Depth 기반 근거리 장애물 표시
  - 건축도면과 현장 좌표 정합
  - 경량 semantic_result 생성
- **Field Tablet Web/App**
  - JPEG/PNG 구조도 등록
  - 축척·시작 위치·출입구 설정
  - Mission 저장 및 ACTIVE 전환
  - 실시간 요구조자/Depth 장애물 화면
  - Host 승인 완료 후 최종 Rescue Map 표시
- **Windows Host**
  - UWB semantic_result 수신
  - 요구조자·위험구역·경로·팀 배치 검토 및 수정
  - Undo/Redo와 Approved Plan 생성
  - Approved Plan UWB 재전송
- **UWB**
  - ESP32 + DWM1000 기반
  - 패킷 분할, ACK/NACK, 재전송, 저장형 큐
  - 대용량 원본 영상 대신 핵심 구조 JSON만 전송

## 통신 원칙

| 경로 | 전송 내용 | 통신 |
|---|---|---|
| Tablet → Jetson | 구조도, Mission 설정, ACTIVE | Wi-Fi / HTTP |
| Jetson → Host | semantic_result: 요구조자·장애물·위험·경로 | UWB |
| Host → Jetson | Approved Plan | UWB |
| Jetson → Tablet | 실시간 비전, 현재 결과, 최종 승인 지도 | Wi-Fi / HTTP |

구조도와 카메라 영상은 UWB로 보내지 않습니다. UWB는 통신이 제한된 재난 환경에서 반드시 전달해야 하는 정제된 구조정보에 집중합니다.

## 주요 디렉터리

```text
deploy/
  host_windows/       Windows Host 설치·실행
  jetson/             Jetson 전체 스택 실행
  tablet_android/     Tablet 빌드
scripts/
  mediapipe_person_bridge.py
  vision_server.py
src/
  d_slam/             SLAM, Jetson API, Tablet App
  host/               Host API, 검토 UI, 저장소
  uwb/                UWB protocol/runtime/interfaces
```

## Jetson 실행

최초 설치 후 환경 파일을 준비합니다.

```bash
cp src/d_slam/config/jetson.env.example src/d_slam/config/jetson.env
cp src/uwb/config/jetson.env.example src/uwb/config/jetson.env
```

장비 주소와 Serial 포트를 환경에 맞게 수정한 뒤:

```bash
source /opt/ros/humble/setup.bash
./deploy/jetson/start.sh
```

MediaPipe bridge와 현장 비전 서버는 별도 터미널에서 실행합니다.

```bash
source /opt/ros/humble/setup.bash
source data/jetson_colcon/install/setup.bash
source ~/mediapipe_test/bin/activate

python scripts/mediapipe_person_bridge.py
```

```bash
source /opt/ros/humble/setup.bash
source data/jetson_colcon/install/setup.bash
source ~/mediapipe_test/bin/activate

python scripts/vision_server.py
```

기본 서비스:

- Jetson API: `http://<JETSON_IP>:8001`
- Vision Server: `http://<JETSON_IP>:8091`
- Person view: `/person.jpg`
- Depth obstacle view: `/depth.jpg`

## Windows Host 실행

PowerShell 실행 정책이 막는 경우 현재 창에만 허용합니다.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

최초 1회:

```powershell
.\deploy\host_windows\setup.ps1
```

실행:

```powershell
.\deploy\host_windows\start.ps1 `
  -BindHost 0.0.0.0 `
  -Port 8000
```

## Tablet Web 빌드

```powershell
cd src\d_slam\flutter_app
flutter pub get
flutter build web `
  --release `
  --dart-define=JETSON_API_BASE_URL=http://<JETSON_IP>:8001
```

정적 서버 예시:

```powershell
py -m http.server 8080 `
  --bind 0.0.0.0 `
  --directory build\web
```

## 운영 흐름

1. Tablet에서 사고 전 구조도와 Mission 정보를 등록합니다.
2. Mission을 ACTIVE로 전환하면 Jetson이 즉시 적용하고 Host에 HTTP로 동기화합니다.
3. Jetson은 RGB-D SLAM과 AI 분석으로 semantic_result를 생성합니다.
4. semantic_result를 UWB로 Host에 전달합니다.
5. 지휘관이 Host에서 요구조자·위험·경로·팀 배치를 검토·수정합니다.
6. Approved Plan을 UWB로 Jetson에 반환합니다.
7. Tablet의 **최종 지도** 탭에 승인 결과가 자동 반영됩니다.

## 릴리스 원칙

`final` 브랜치는 촬영용 결과 생성 스크립트, 임시 JSON, 런타임 데이터, 빌드 산출물 및 테스트 전용 파일을 제외한 제출·배포용 소스만 포함합니다.