"""Run the Host API with ``python -m host_app.api``."""

from __future__ import annotations

import argparse
import logging
import math
import os
import sys
import threading
import time
from pathlib import Path

from ..map_editor import NormalizationOptions
from ..ros_client import HostBridgeFacade, RclpyBridgeClient, SerialBridgeClient
from .app import create_app
from .service import HostApiService


DEFAULT_WEB_ROOT = (
    Path(__file__).resolve().parents[3] / "flutter_app" / "build" / "web"
)


def _env_int(name: str, default: int, *aliases: str) -> int:
    raw = next(
        (
            os.environ[key]
            for key in (name, *aliases)
            if key in os.environ and os.environ[key].strip()
        ),
        str(default),
    )
    try:
        return int(raw)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{name} must be an integer") from error


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{name} must be numeric") from error


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_port() -> str:
    return os.environ.get(
        "AI_RESCUE_UWB_SERIAL_PORT",
        os.environ.get("AI_RESCUE_UWB_PORT", ""),
    ).strip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI Rescue Box Host FastAPI backend")
    parser.add_argument(
        "--host", default=os.environ.get("AI_RESCUE_API_HOST", "127.0.0.1")
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("AI_RESCUE_API_PORT", "8000")),
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(os.environ.get("AI_RESCUE_HOST_DATA", Path.cwd() / "data")),
    )
    parser.add_argument(
        "--web-root",
        type=Path,
        default=Path(os.environ.get("AI_RESCUE_HOST_WEB_ROOT", DEFAULT_WEB_ROOT)),
        help="Flutter Web build directory; served at / when index.html exists",
    )
    parser.add_argument(
        "--bridge-mode",
        choices=("offline", "serial", "ros"),
        default=os.environ.get("AI_RESCUE_UWB_BRIDGE_MODE", "serial"),
        help=(
            "serial is the ROS-free Windows product default; ros keeps the "
            "existing optional development adapter"
        ),
    )
    parser.add_argument(
        "--no-ros",
        action="store_true",
        help="compatibility alias: replace bridge-mode ros with serial",
    )
    parser.add_argument(
        "--uwb-port",
        default=_env_port(),
        help="ESP32 serial port; blank starts disconnected",
    )
    parser.add_argument(
        "--uwb-baud",
        type=int,
        default=_env_int(
            "AI_RESCUE_UWB_BAUD", 460800, "AI_RESCUE_UWB_BAUDRATE"
        ),
    )
    parser.add_argument(
        "--uwb-spool",
        type=Path,
        default=Path(
            os.environ.get(
                "AI_RESCUE_UWB_SPOOL", Path.cwd() / "data" / "uwb_spool" / "host"
            )
        ),
    )
    parser.add_argument(
        "--uwb-auto-discover",
        action="store_true",
        default=_env_bool("AI_RESCUE_UWB_AUTO_DISCOVER", False),
        help="select a serial port only when exactly one candidate is present",
    )
    parser.add_argument(
        "--firmware-ack-timeout",
        type=float,
        default=_env_float("AI_RESCUE_UWB_FIRMWARE_ACK_TIMEOUT", 2.0),
    )
    parser.add_argument(
        "--firmware-max-attempts",
        type=int,
        default=_env_int("AI_RESCUE_UWB_FIRMWARE_MAX_ATTEMPTS", 3),
    )
    parser.add_argument(
        "--stored-ack-timeout",
        type=float,
        default=_env_float("AI_RESCUE_UWB_STORED_ACK_TIMEOUT", 5.0),
    )
    parser.add_argument(
        "--application-ack-timeout",
        type=float,
        default=_env_float("AI_RESCUE_UWB_APPLICATION_ACK_TIMEOUT", 30.0),
    )
    parser.add_argument(
        "--serial-send-timeout",
        type=float,
        default=_env_float("AI_RESCUE_UWB_SERIAL_SEND_TIMEOUT", 20.0),
    )
    parser.add_argument(
        "--send-queue-limit",
        type=int,
        default=_env_int("AI_RESCUE_UWB_SEND_QUEUE_LIMIT", 32),
        help="maximum Host serial lines waiting for a disconnected device",
    )
    parser.add_argument(
        "--reconnect-initial-delay",
        type=float,
        default=_env_float("AI_RESCUE_UWB_RECONNECT_INITIAL_DELAY", 0.25),
    )
    parser.add_argument(
        "--reconnect-max-delay",
        type=float,
        default=_env_float("AI_RESCUE_UWB_RECONNECT_MAX_DELAY", 3.0),
    )
    parser.add_argument(
        "--reconnect-attempts",
        type=int,
        default=_env_int("AI_RESCUE_UWB_RECONNECT_ATTEMPTS", 6),
    )
    parser.add_argument(
        "--reconnect-cooldown",
        type=float,
        default=_env_float("AI_RESCUE_UWB_RECONNECT_COOLDOWN", 5.0),
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=Path(os.environ.get("AI_RESCUE_LOG_DIR", Path.cwd() / "data" / "logs")),
    )
    parser.add_argument(
        "--shutdown-file",
        type=Path,
        default=(
            Path(os.environ["AI_RESCUE_SHUTDOWN_FILE"])
            if os.environ.get("AI_RESCUE_SHUTDOWN_FILE", "").strip()
            else None
        ),
        help="optional local sentinel file used by deployment stop scripts",
    )
    parser.add_argument(
        "--cors-origin",
        action="append",
        default=None,
        help="allowed browser origin; repeat for multiple origins",
    )
    parser.add_argument(
        "--map-max-dimension",
        type=int,
        default=_env_int("AI_RESCUE_MAP_MAX_DIMENSION", 2048),
        help="longest transmission-map edge in pixels",
    )
    parser.add_argument(
        "--jpeg-quality",
        type=int,
        default=_env_int("AI_RESCUE_JPEG_QUALITY", 82),
        help="transmission JPEG quality (1-95)",
    )
    parser.add_argument(
        "--png-compress-level",
        type=int,
        default=_env_int("AI_RESCUE_PNG_COMPRESS_LEVEL", 6),
        help="transmission PNG compression (0-9)",
    )
    parser.add_argument(
        "--max-map-input-mib",
        type=float,
        default=_env_float("AI_RESCUE_MAX_MAP_INPUT_MIB", 50.0),
        help="maximum original map size in MiB",
    )
    parser.add_argument(
        "--max-map-pixels",
        type=int,
        default=_env_int("AI_RESCUE_MAX_MAP_PIXELS", 40_000_000),
        help="maximum decoded map pixels",
    )
    parser.add_argument(
        "--max-artifact-mib",
        type=float,
        default=_env_float("AI_RESCUE_MAX_ARTIFACT_MIB", 10.0),
        help="Host spool artifact limit in MiB (protocol ceiling: 10)",
    )
    parser.add_argument(
        "--transfer-timeout",
        type=float,
        default=_env_float("AI_RESCUE_TRANSFER_TIMEOUT", 45.0),
        help="bounded wait per artifact in seconds",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate imports/settings without opening ROS or serial hardware",
    )
    return parser


def _positive_finite(value: float, name: str) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be positive and finite")


def _configure_logging(directory: Path) -> None:
    directory = directory.expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    file_handler = logging.FileHandler(directory / "host-runtime.log", encoding="utf-8")
    stream_handler = logging.StreamHandler()
    file_handler.setFormatter(formatter)
    stream_handler.setFormatter(formatter)
    logging.basicConfig(
        level=os.environ.get("AI_RESCUE_LOG_LEVEL", "INFO").upper(),
        handlers=[file_handler, stream_handler],
        force=True,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.no_ros and args.bridge_mode == "ros":
        args.bridge_mode = "serial"
    try:
        if not args.host.strip():
            raise ValueError("--host must not be empty")
        if not 1 <= args.port <= 65535:
            raise ValueError("--port must be between 1 and 65535")
        if args.uwb_baud <= 0:
            raise ValueError("--uwb-baud must be positive")
        if args.firmware_max_attempts <= 0 or args.reconnect_attempts <= 0:
            raise ValueError("UWB attempt counts must be positive")
        if args.send_queue_limit <= 0:
            raise ValueError("--send-queue-limit must be positive")
        for value, name in (
            (args.max_map_input_mib, "--max-map-input-mib"),
            (args.max_artifact_mib, "--max-artifact-mib"),
            (args.transfer_timeout, "--transfer-timeout"),
            (args.firmware_ack_timeout, "--firmware-ack-timeout"),
            (args.stored_ack_timeout, "--stored-ack-timeout"),
            (args.application_ack_timeout, "--application-ack-timeout"),
            (args.serial_send_timeout, "--serial-send-timeout"),
            (args.reconnect_initial_delay, "--reconnect-initial-delay"),
            (args.reconnect_max_delay, "--reconnect-max-delay"),
            (args.reconnect_cooldown, "--reconnect-cooldown"),
        ):
            _positive_finite(value, name)
        if args.reconnect_max_delay < args.reconnect_initial_delay:
            raise ValueError(
                "--reconnect-max-delay must be >= --reconnect-initial-delay"
            )
        max_artifact_bytes = round(args.max_artifact_mib * 1024 * 1024)
        if max_artifact_bytes < 1:
            raise ValueError("--max-artifact-mib is too small")
        if max_artifact_bytes > 10 * 1024 * 1024:
            raise ValueError(
                "--max-artifact-mib cannot exceed the UWB protocol ceiling (10 MiB)"
            )
        options = NormalizationOptions(
            max_dimension=args.map_max_dimension,
            jpeg_quality=args.jpeg_quality,
            png_compress_level=args.png_compress_level,
            max_input_bytes=round(args.max_map_input_mib * 1024 * 1024),
            max_pixels=args.max_map_pixels,
        )
    except (ValueError, OverflowError) as error:
        print(f"[ERROR] invalid Host backend settings: {error}", file=sys.stderr)
        return 2

    if args.check:
        from ai_rescue_uwb_common import ManagedSerialTransport
        from ..map_editor import RasterMapImporter
        from ..mission.models import SCHEMA_VERSION

        assert RasterMapImporter and HostBridgeFacade and ManagedSerialTransport and create_app
        print(
            "AI Rescue Box Host backend/serial path OK "
            f"(schema {SCHEMA_VERSION}, mode={args.bridge_mode}, hardware not opened)"
        )
        return 0

    _configure_logging(args.log_dir)
    bridge = HostBridgeFacade()
    if args.bridge_mode == "serial":
        bridge.attach(
            SerialBridgeClient(
                port=args.uwb_port,
                baudrate=args.uwb_baud,
                spool_dir=args.uwb_spool,
                auto_discover=args.uwb_auto_discover,
                firmware_ack_timeout=args.firmware_ack_timeout,
                firmware_max_attempts=args.firmware_max_attempts,
                stored_ack_timeout=args.stored_ack_timeout,
                application_ack_timeout=args.application_ack_timeout,
                reconnect_initial_delay=args.reconnect_initial_delay,
                reconnect_max_delay=args.reconnect_max_delay,
                reconnect_attempts=args.reconnect_attempts,
                reconnect_cooldown=args.reconnect_cooldown,
                send_timeout=args.serial_send_timeout,
                max_pending_sends=args.send_queue_limit,
            )
        )
    elif args.bridge_mode == "ros":
        try:
            bridge.attach(RclpyBridgeClient())
        except RuntimeError as error:
            raise SystemExit(f"ROS2 Bridge client startup failed: {error}") from error

    service = HostApiService(
        args.data_dir,
        bridge=bridge,
        normalization_options=options,
        max_artifact_bytes=max_artifact_bytes,
        transfer_timeout=args.transfer_timeout,
    )
    app = create_app(service, cors_origins=args.cors_origin)

    web_root = args.web_root.expanduser().resolve()
    if web_root.is_dir() and (web_root / "index.html").is_file():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=web_root, html=True), name="host-web")
        logging.getLogger(__name__).info("Host Flutter Web root=%s", web_root)
    else:
        logging.getLogger(__name__).warning(
            "Host Flutter Web build not found at %s; backend-only mode", web_root
        )

    try:
        import uvicorn
    except ImportError as error:
        service.close()
        bridge.close()
        raise SystemExit(
            "uvicorn is required; install host_app/requirements.txt"
        ) from error
    shutdown_file = (
        args.shutdown_file.expanduser().resolve() if args.shutdown_file is not None else None
    )
    if shutdown_file is not None:
        shutdown_file.parent.mkdir(parents=True, exist_ok=True)
        shutdown_file.unlink(missing_ok=True)
    server = uvicorn.Server(uvicorn.Config(app, host=args.host, port=args.port))

    def watch_shutdown_file() -> None:
        assert shutdown_file is not None
        while not server.should_exit:
            if shutdown_file.exists():
                logging.getLogger(__name__).info(
                    "Host shutdown sentinel received: %s", shutdown_file
                )
                server.should_exit = True
                return
            time.sleep(0.25)

    watcher = None
    if shutdown_file is not None:
        watcher = threading.Thread(
            target=watch_shutdown_file,
            name="host-shutdown-sentinel",
            daemon=True,
        )
        watcher.start()
    try:
        server.run()
    finally:
        service.close()
        bridge.close()
        if shutdown_file is not None:
            shutdown_file.unlink(missing_ok=True)
        if watcher is not None and watcher is not threading.current_thread():
            watcher.join(timeout=1.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
