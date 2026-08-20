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
        "deploy/host_windows/setup.ps1",
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


def test_windows_host_two_command_setup_contract() -> None:
    setup = read("deploy/host_windows/setup.ps1")
    readme = read("deploy/host_windows/README.md")
    start = read("deploy/host_windows/start.ps1")

    assert 'Join-Path $PSScriptRoot "install.ps1"' in setup
    assert 'Join-Path $PSScriptRoot "build_web.ps1"' in setup
    assert 'Join-Path $RepoRoot "src\\host\\config\\host.env"' in setup
    assert "if (-not (Test-Path $Config))" in setup
    assert "Copy-Item $Example $Config" in setup
    assert "existing host.env preserved" in setup
    assert "AI_RESCUE_UWB_SERIAL_PORT" in setup
    assert "was NOT auto-selected" in setup
    assert "start.ps1" in setup

    quick_start = readme.split("## setup.ps1이 준비하는 것", maxsplit=1)[0]
    assert ".\\deploy\\host_windows\\setup.ps1" in quick_start
    assert ".\\deploy\\host_windows\\start.ps1" in quick_start
    assert ".\\deploy\\host_windows\\stop.ps1" in quick_start
    assert ".\\deploy\\host_windows\\status.ps1" in quick_start
    assert "Advanced / Debug / Manual Setup" in readme
    assert "install.ps1" in readme
    assert "build_web.ps1" in readme

    # Stage 5A runtime entry point remains intact; setup is only a wrapper.
    assert "Start-Process -FilePath $PythonExe" in start
    assert 'BridgeMode = "serial"' in start
    assert "A missing ESP32 is reported as DISCONNECTED" in start
