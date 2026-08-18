"""Run the Host API with ``python3 -m host_app.api``."""

from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path

from ..map_editor import NormalizationOptions
from ..ros_client import HostBridgeFacade, RclpyBridgeClient
from .app import create_app
from .service import HostApiService


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{name} must be an integer") from error


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{name} must be numeric") from error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI Rescue Box Host FastAPI backend")
    parser.add_argument("--host", default=os.environ.get("AI_RESCUE_API_HOST", "127.0.0.1"))
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
    parser.add_argument("--no-ros", action="store_true")
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
        help="validate backend/core imports and settings, then exit",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if not 1 <= args.port <= 65535:
            raise ValueError("--port must be between 1 and 65535")
        if not math.isfinite(args.max_map_input_mib) or args.max_map_input_mib <= 0:
            raise ValueError("--max-map-input-mib must be positive and finite")
        if not math.isfinite(args.max_artifact_mib) or args.max_artifact_mib <= 0:
            raise ValueError("--max-artifact-mib must be positive and finite")
        if not math.isfinite(args.transfer_timeout) or args.transfer_timeout <= 0:
            raise ValueError("--transfer-timeout must be positive and finite")
        max_artifact_bytes = round(args.max_artifact_mib * 1024 * 1024)
        if max_artifact_bytes < 1:
            raise ValueError("--max-artifact-mib must be positive")
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
        from ..map_editor import RasterMapImporter
        from ..mission.models import SCHEMA_VERSION

        assert RasterMapImporter and HostBridgeFacade and create_app
        print(f"AI Rescue Box Host backend/core OK (schema {SCHEMA_VERSION})")
        return 0
    bridge = HostBridgeFacade()
    if not args.no_ros:
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
    try:
        import uvicorn
    except ImportError as error:
        service.close()
        bridge.close()
        raise SystemExit(
            "uvicorn is required; install host_app/requirements.txt"
        ) from error
    try:
        uvicorn.run(app, host=args.host, port=args.port)
    finally:
        service.close()
        bridge.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
