# Stage 5B Measurement Template

> Stage 5A에서는 숫자를 채우지 않는다. 실제 장비에서 동일 조건을 최소 3회 반복하고 raw 값과 요약 값을 함께 남긴다.

## A. 시험 환경

| 항목 | 값 |
|---|---|
| 날짜/시간 | |
| 시험자 | |
| `app` commit SHA — Windows | |
| `app` commit SHA — Jetson | |
| Windows/Python version | |
| JetPack/Ubuntu/ROS version | |
| Jetson power mode | |
| Galaxy Tab model/Android version | |
| Astra model/driver | |
| Host ESP32/DWM1000 board | |
| Jetson ESP32/DWM1000 board | |
| Host Serial port / baud | |
| Jetson Serial path / baud | |
| Firmware Host/Jetson build env | |
| YOLO model path/hash/input shape | |
| Network mode (Hotspot/USB/LAN) | |
| Jetson IP/API URL | |
| Stage 4 config path/hash | |
| 인터넷 연결 상태 | |

## B. UWB Artifact 전송 — 각 전송별 기록

| Run | 방향 | Artifact type | Transfer ID | Bytes | SHA 일치 | Firmware frame ACK | Retry count | Peer stored ACK latency (ms) | Application ACK latency (ms) | Total latency (ms) | 성공/실패 | Error/NACK |
|---:|---|---|---|---:|---|---|---:|---:|---:|---:|---|---|
| 1 | Host→Jetson | base_map | | | | | | | N/A | | | |
| 1 | Host→Jetson | mission_manifest | | | | | | | | | | |
| 1 | Jetson→Host | semantic_result | | | | | | | | | | |
| 1 | Jetson→Host | map_preview | | | | | | | | | | |
| 1 | Host→Jetson | approved_plan | | | | | | | | | | |
| 2 | | | | | | | | | | | | |
| 3 | | | | | | | | | | | | |

## C. Serial reconnect/removal

| Run | 장치 | 분리 시각 | disconnect 감지 (ms) | reconnect attempts | cooldown cycles | 재연결 시각 | 복구 시간 (ms) | API process 유지 | 진행 중 transfer 결과 | 비고 |
|---:|---|---|---:|---:|---:|---|---:|---|---|---|
| 1 | Host ESP32 | | | | | | | | | |
| 1 | Jetson ESP32 | | | | | | | | | |
| 2 | | | | | | | | | | |

## D. Astra / RTAB-Map / TF

| Run | RGB Hz | Depth Hz | Camera info | RGB/Depth timestamp skew (ms) | RTAB odom Hz | Map update Hz | Tracking state | Tracking loss count | map↔odom TF | 비고 |
|---:|---:|---:|---|---:|---:|---:|---|---:|---|---|
| 1 | | | | | | | | | | |
| 2 | | | | | | | | | | |
| 3 | | | | | | | | | | |

## E. YOLO + Depth + Stage 4 Analysis

| Run | YOLO load | Inference time (ms) | Detection count | Depth 3D association | Risk time (ms) | Alignment time (ms) | Alignment accepted/confidence | Traversability time (ms) | Route/safe-zone time (ms) | 전체 analysis time (ms) | 성공/실패/Error |
|---:|---|---:|---:|---|---:|---:|---|---:|---:|---:|---|
| 1 | | | | | | | | | | | |
| 2 | | | | | | | | | | | |
| 3 | | | | | | | | | | | |

Alignment 상세:

| Run | translation search/step | yaw search/step | overlap | coverage | known/occupied cells | confidence | rejection reason | config change |
|---:|---|---|---:|---:|---|---:|---|---|
| 1 | | | | | | | | |
| 2 | | | | | | | | |
| 3 | | | | | | | | |

## F. Tablet/API/Network

| Run | Network mode | Tablet→health | Tablet→status | Mission 조회 | Map preview | Result 조회 | WebSocket/event | API latency (ms) | 연결 끊김/오류 |
|---:|---|---|---|---|---|---|---|---:|---|
| 1 | | | | | | | | | |
| 2 | | | | | | | | | |
| 3 | | | | | | | | | |

## G. Offline E2E

| Run | Internet off 확인 | Host Mission→Jetson | Mission READY | Analysis | Result→Host | Approved Plan→Jetson | 외부 서버/DNS 의존 없음 | 전체 성공 | 전체 시간 | 실패 단계/로그 |
|---:|---|---|---|---|---|---|---|---|---:|---|
| 1 | | | | | | | | | | |
| 2 | | | | | | | | | | |
| 3 | | | | | | | | | | |

## H. 요약

| 지표 | 성공 횟수 / 전체 | 평균 | P50 | P95 | 최댓값 | 비고 |
|---|---:|---:|---:|---:|---:|---|
| Host→Jetson Mission 성공률 | | | | | | |
| Jetson→Host Result 성공률 | | | | | | |
| Firmware/packet retry | | | | | | |
| Peer stored ACK latency | | | | | | |
| Application ACK latency | | | | | | |
| Preview transfer latency | | | | | | |
| Analysis 전체 시간 | | | | | | |
| Offline E2E 성공률 | | | | | | |

## I. 판정

- [ ] 실제 Windows Host 설치 성공
- [ ] 실제 Host COM Serial open/재연결 성공
- [ ] 실제 ESP32 두 대 flash 성공
- [ ] 실제 DWM1000 Radio 송수신 성공
- [ ] 실제 Jetson deployment 성공
- [ ] 실제 Astra RGB-D stream 성공
- [ ] 실제 RTAB-Map tracking 성공
- [ ] 실제 ONNX inference 성공
- [ ] 실제 Galaxy Tab APK 설치/연결 성공
- [ ] 실제 Jetson Hotspot 또는 선택 network 성공
- [ ] 실제 Host↔Jetson Mission/Result/Approved Plan UWB E2E 성공
- [ ] 실제 인터넷 차단 offline E2E 성공

최종 판정/미해결 이슈:

```text

```
