"""Background HTTP mirror for the Tablet-selected ACTIVE Mission."""

from __future__ import annotations

import base64
import json
import os
import threading
import urllib.request
from typing import Any, Mapping

from .manager import MissionManager


DEFAULT_HOST_API_URL = "http://192.168.0.10:8000"
MISSION_SYNC_PATH = "/api/v1/jetson/missions/sync"


class HostMissionSync:
    """Mirror ACTIVE Mission metadata and the base map without blocking Tablet UI."""

    def __init__(
        self,
        manager: MissionManager,
        events: Any,
        *,
        url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.manager = manager
        self.events = events

        explicit_endpoint = (
            url
            or os.environ.get("AI_RESCUE_HOST_MISSION_SYNC_URL", "").strip()
        )
        if explicit_endpoint:
            self.url = explicit_endpoint
        else:
            host_base = (
                os.environ.get("AI_RESCUE_HOST_API_URL", "").strip()
                or DEFAULT_HOST_API_URL
            )
            self.url = host_base.rstrip("/") + MISSION_SYNC_PATH

        configured_timeout = os.environ.get(
            "AI_RESCUE_HOST_SYNC_TIMEOUT_SECONDS", "10"
        )
        self.timeout = max(
            0.1,
            float(timeout if timeout is not None else configured_timeout),
        )

    def queue_active(self, mission_id: str, mission_version: int) -> Mapping[str, Any]:
        payload = {
            "mission_id": mission_id,
            "mission_version": mission_version,
            "state": "queued",
            "transport": "http",
        }
        self.events.publish("mission.host_sync_queued", payload)
        threading.Thread(
            target=self._send_active,
            args=(mission_id, mission_version),
            name=f"host-mission-sync-{mission_id}-v{mission_version}",
            daemon=True,
        ).start()
        return payload

    def _send_active(self, mission_id: str, mission_version: int) -> None:
        try:
            mission = self.manager.load_mission(mission_id, mission_version)
            body = json.dumps(
                {
                    "manifest": mission.manifest.to_dict(),
                    "base_map": base64.b64encode(
                        mission.base_map_path.read_bytes()
                    ).decode("ascii"),
                },
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")

            request = urllib.request.Request(
                self.url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                response_payload = json.loads(
                    response.read(64 * 1024).decode("utf-8")
                )
                status = int(getattr(response, "status", 200))
                if not 200 <= status < 300:
                    raise RuntimeError(f"Host Mission sync returned HTTP {status}")

            self.events.publish(
                "mission.host_sync_completed",
                {
                    "mission_id": mission_id,
                    "mission_version": mission_version,
                    "state": "ACTIVE",
                    "transport": "http",
                    "response": response_payload,
                },
            )
        except Exception as error:
            self.events.publish(
                "mission.host_sync_failed",
                {
                    "mission_id": mission_id,
                    "mission_version": mission_version,
                    "transport": "http",
                    "error": str(error),
                },
            )


__all__ = [
    "DEFAULT_HOST_API_URL",
    "MISSION_SYNC_PATH",
    "HostMissionSync",
]