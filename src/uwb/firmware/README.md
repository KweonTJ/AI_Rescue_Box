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

### thotro v0.9 ESP32 compile compatibility

기존 dependency `thotro/arduino-dw1000 v0.9`는 `DW1000.cpp`에서 `SPI.usingInterrupt()`를 호출하지만 ESP32 Arduino `SPIClass`에는 해당 API가 없다. `platformio.ini`의 `post:scripts/patch_dw1000_esp32.py`는 dependency가 resolve된 뒤 **그 한 guard만** `ESP32`에서도 건너뛰도록 바꾼다.

- dependency version은 v0.9로 고정한다.
- 예상한 v0.9 source 문구가 달라지면 build를 즉시 실패시킨다.
- `src/uwb/firmware/src/uwb_node/main.cpp`, Radio framing, ACK/retry 로직은 수정하지 않는다.
- 이는 compile 호환성 보완일 뿐 DWM1000 Radio 실장 성공을 의미하지 않는다.

## Flash (Stage 5B only)

`platformio.ini`에는 `/dev/ttyACM0`, `/dev/ttyUSB0`, `COM3` 같은 machine port를 고정하지 않는다.

```bash
pio run -e host_node -t upload --upload-port <HOST_ESP32_PORT>
pio run -e jetson_node -t upload --upload-port <JETSON_ESP32_PORT>
```

`pio run` compile 성공은 Source/build 호환만 의미한다. ESP32 flashing, DWM1000 Radio 송수신, ACK latency와 packet loss는 `docs/stage5_hardware_validation.md`에서 별도로 검증한다.
