# Optional stable ESP32 device name

Stage 5A does not know the actual ESP32 USB VID/PID and therefore does not install or enable a rule.

Stage 5B에서 각 ESP32를 연결한 뒤 다음으로 값을 확인한다.

```bash
python3 -m serial.tools.list_ports -v
udevadm info --attribute-walk --name=/dev/ttyACM0
```

`99-ai-rescue-uwb.rules.example`의 `<VID>`/`<PID>`를 **실제 확인 값**으로 바꾸고 필요하면 serial number까지 조건에 추가한다. 그 후 사용자가 검토한 규칙만 `/etc/udev/rules.d/`에 복사한다. 확인되지 않은 값으로 규칙을 활성화하지 않는다.
