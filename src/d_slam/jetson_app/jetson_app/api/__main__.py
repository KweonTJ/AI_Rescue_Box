"""Run the Jetson local FastAPI service."""

from __future__ import annotations

import os


def main() -> int:
    try:
        import uvicorn
    except ImportError as error:
        raise SystemExit(f"uvicorn is required: {error}") from error

    host = os.environ.get("AI_RESCUE_JETSON_API_HOST", "0.0.0.0").strip()
    if not host:
        raise SystemExit("AI_RESCUE_JETSON_API_HOST must not be empty")
    try:
        port = int(os.environ.get("AI_RESCUE_JETSON_API_PORT", "8001"))
    except ValueError as error:
        raise SystemExit("AI_RESCUE_JETSON_API_PORT must be an integer") from error
    if not 1 <= port <= 65535:
        raise SystemExit("AI_RESCUE_JETSON_API_PORT must be between 1 and 65535")

    uvicorn.run(
        "jetson_app.api.app:create_app",
        factory=True,
        host=host,
        port=port,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
