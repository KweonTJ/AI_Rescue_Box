import importlib.util

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("fastapi") is None,
    reason="fastapi not installed",
)


def test_fastapi_health():
    from fastapi.testclient import TestClient
    from jetson_app.api import create_app

    client = TestClient(create_app())
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["stage"] == "stage01"


def test_tablet_websocket_uses_api_event_envelope(tmp_path):
    from fastapi.testclient import TestClient

    from jetson_app.api import create_app
    from jetson_app.api.service import JetsonApiService
    from jetson_app.mission import MissionManager

    service = JetsonApiService(MissionManager(tmp_path / "missions"), mode="mock")
    client = TestClient(create_app(service))

    with client.websocket_connect("/api/v1/events/ws") as websocket:
        event = websocket.receive_json()

    assert event["event_type"] == "events.connected"
    assert isinstance(event["sequence"], int) and event["sequence"] > 0
    assert isinstance(event["instance_id"], str) and event["instance_id"]
    assert event["payload"]["client"] == "tablet"
