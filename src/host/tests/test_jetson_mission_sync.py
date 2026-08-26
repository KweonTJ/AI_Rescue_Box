from __future__ import annotations

import base64
import hashlib
import json
from io import BytesIO
from pathlib import Path
import threading
import time
from urllib import request as urllib_request

from PIL import Image
import uvicorn

from host_app.api import create_app
from host_app.api.service import HostApiService


def _sync_payload() -> dict:
    output = BytesIO()
    Image.new("RGB", (12, 8), "white").save(output, format="PNG")
    base_map = output.getvalue()
    digest = hashlib.sha256(base_map).hexdigest()
    return {
        "manifest": {
            "schema_version": "1.0",
            "mission_id": "jetson-sync-test",
            "mission_version": 1,
            "artifact_version": 1,
            "mission_name": "Jetson Mission",
            "created_at": "2026-08-26T00:00:00Z",
            "base_map": {
                "filename": "base_map.png",
                "sha256": digest,
                "width": 12,
                "height": 8,
            },
            "meters_per_pixel": 0.1,
            "robot_start": {"x": 1.0, "y": 1.0, "yaw": 0.0},
            "entrances": [{"x": 0.0, "y": 0.0}],
            "available_teams": 1,
            "available_rescuers": 2,
            "coordinate_frame": "mission_map",
            "units": "meters",
            "source": "tablet",
            "confidence": 1.0,
        },
        "base_map": base64.b64encode(base_map).decode("ascii"),
    }


def _post_sync(port: int, payload: dict) -> tuple[int, dict]:
    request = urllib_request.Request(
        f"http://127.0.0.1:{port}/api/v1/jetson/missions/sync",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib_request.urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def test_exact_jetson_sync_route_is_idempotent_and_activates(tmp_path: Path) -> None:
    service = HostApiService(tmp_path / "host")
    payload = _sync_payload()
    server = uvicorn.Server(
        uvicorn.Config(create_app(service=service), host="127.0.0.1", port=0, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    try:
        thread.start()
        deadline = time.monotonic() + 5
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        port = server.servers[0].sockets[0].getsockname()[1]

        first_status, first = _post_sync(port, payload)
        assert first_status == 200
        assert first["state"] == "ACTIVE"
        assert first["reused"] is False

        mission_dir = service.store.mission_dir("jetson-sync-test", 1)
        result_sentinel = mission_dir / "results" / "semantic_result_v1.json"
        plan_sentinel = mission_dir / "plans" / "approved_plan_v1.json"
        result_sentinel.parent.mkdir()
        plan_sentinel.parent.mkdir()
        result_sentinel.write_bytes(b"semantic-result-sentinel")
        plan_sentinel.write_bytes(b"approved-plan-sentinel")

        second_status, second = _post_sync(port, payload)

        assert second_status == 200
        assert second["reused"] is True
        assert service.store.list_versions("jetson-sync-test") == (1,)
        assert service.status()["active_mission"] == {
            "mission_id": "jetson-sync-test",
            "mission_version": 1,
        }
        assert result_sentinel.read_bytes() == b"semantic-result-sentinel"
        assert plan_sentinel.read_bytes() == b"approved-plan-sentinel"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        service.close()
