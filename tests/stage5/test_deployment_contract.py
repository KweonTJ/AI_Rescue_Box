from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_stage5_deployment_contracts() -> None:
    config = read("src/host/config/host.env.example")
    start = read("deploy/host_windows/start.ps1")
    install = read("deploy/host_windows/install.ps1")
    assert "AI_RESCUE_UWB_BRIDGE_MODE=serial" in config
    assert "AI_RESCUE_UWB_SERIAL_PORT=\n" in config
    assert 'BridgeMode = "serial"' in start
    assert "EnableRosBridge" in start
    assert "Get-Command flutter" not in install
    assert "flutter pub" not in install.lower()
    assert "needed only for build_web.ps1" in install
    assert "[serial]" in install


    # Jetson/firmware machine values remain configurable.
    config = read("src/uwb/config/jetson.env.example")
    platformio = read("src/uwb/firmware/platformio.ini")
    assert "AI_RESCUE_UWB_SERIAL_PORT=\n" in config
    assert "upload_port" not in platformio
    assert "monitor_port" not in platformio
    assert "doubleclick.lab.cbnu.ac.kr" not in config
    assert "AI_RESCUE_ROLE_HOST" in platformio
    assert "AI_RESCUE_ROLE_JETSON" in platformio


    # Required lifecycle scripts and validation runbooks are present.
    required = [
        "deploy/host_windows/install.ps1",
        "deploy/host_windows/start.ps1",
        "deploy/host_windows/stop.ps1",
        "deploy/host_windows/status.ps1",
        "deploy/jetson/install.sh",
        "deploy/jetson/start.sh",
        "deploy/jetson/stop.sh",
        "deploy/jetson/status.sh",
        "deploy/tablet_android/build_apk.sh",
        "docs/stage5_hardware_validation.md",
        "docs/stage5_measurement_template.md",
    ]
    assert all((ROOT / value).is_file() for value in required)
