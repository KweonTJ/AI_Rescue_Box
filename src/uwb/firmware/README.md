# ESP32 + DWM1000 firmware

같은 Source가 Host-side와 Jetson-side ESP32에 사용된다. 기존 `main.cpp`의 newline Serial framing, `[UWB ACK]`, Radio DATA/ACK, bounded Radio retry, 111-byte application payload를 유지한다. Stage 2 상위 계층의 chunk/SHA/peer-stored/application-applied ACK를 새 protocol로 바꾸지 않는다.

## Role build

```bash
cd src/uwb/firmware
pio run -e host_node
pio run -e jetson_node
```

기존 자동화 호환을 위해 `laptop_node`는 `host_node` alias로 남아 있다.

Role mapping:

- `host_node`: `NODE_ID=1`, `PEER_ID=2`
- `jetson_node`: `NODE_ID=2`, `PEER_ID=1`

DWM1000 SPI/IRQ/RST/SS pin은 기존 `src/uwb_node/main.cpp` 값을 재사용한다. 실제 보드 배선이 다르면 Stage 5B에서 측정/도면 확인 후 수정하며, Stage 5A에서 새 pin을 추측하지 않는다.

## Flash (Stage 5B only)

`platformio.ini`에는 `/dev/ttyACM0`, `/dev/ttyUSB0`, `COM3` 같은 machine port를 고정하지 않는다.

```bash
pio run -e host_node -t upload --upload-port <HOST_ESP32_PORT>
pio run -e jetson_node -t upload --upload-port <JETSON_ESP32_PORT>
```

`pio run` compile 성공은 Source/build 호환만 의미한다. ESP32 flashing, DWM1000 Radio 송수신, ACK latency와 packet loss는 `docs/stage5_hardware_validation.md`에서 별도로 검증한다.
