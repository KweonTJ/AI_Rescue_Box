"""Synchronize Jetson's ACTIVE Mission to the Host over local Wi-Fi HTTP."""
from __future__ import annotations

import base64
import json
import os
from typing import Any, Mapping
from urllib import error as urllib_error
from urllib import request as urllib_request

from .manager import MissionManager


class MissionStatePublisher:
    """Send the canonical manifest and base map without using the UWB link."""

    def __init__(
        self,
        manager: MissionManager,
        host_base_url: str | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> None:
        self.manager = manager
        configured_url = host_base_url or os.environ.get(
            "AI_RESCUE_HOST_API_URL", "http://192.168.0.10:8000"
        )
        self.endpoint = configured_url.rstrip("/") + "/api/v1/jetson/missions/sync"
        self.timeout_seconds = timeout_seconds or float(
            os.environ.get("AI_RESCUE_HOST_SYNC_TIMEOUT_SECONDS", "5")
        )
        if self.timeout_seconds <= 0:
            raise ValueError("Host Mission sync timeout must be positive")

    def publish_active(self, mission_id: str, mission_version: int) -> Mapping[str, Any]:
        applied = self.manager.load_mission(mission_id, mission_version)
        payload = {
            "manifest": applied.manifest.to_dict(),
            "base_map": base64.b64encode(applied.base_map_path.read_bytes()).decode(
                "ascii"
            ),
        }
        request = urllib_request.Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib_request.urlopen(request, timeout=self.timeout_seconds) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Host Mission sync failed with HTTP {error.code}: {detail}"
            ) from error
        except (urllib_error.URLError, TimeoutError, OSError) as error:
            raise RuntimeError(f"Host Mission sync failed: {error}") from error
        if not isinstance(result, Mapping) or result.get("state") != "ACTIVE":
            raise RuntimeError("Host Mission sync returned an invalid response")
        return {
            **dict(result),
            "success": True,
            "transport": "http",
            "endpoint": self.endpoint,
            "mission_id": mission_id,
            "mission_version": mission_version,
        }


__all__ = ["MissionStatePublisher"]
