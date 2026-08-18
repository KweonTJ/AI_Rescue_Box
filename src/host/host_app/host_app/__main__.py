"""Launch the Host FastAPI backend with ``python3 -m host_app``."""

from .api.__main__ import build_parser, main

__all__ = ["build_parser", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
