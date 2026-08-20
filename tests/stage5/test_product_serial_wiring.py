from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

from ai_rescue_uwb_common import (
    ArtifactBridgeCore,
    ArtifactMetadata,
    BridgeEventKind,
    SpoolManager,
    create_memory_link,
)
from host_app.ros_client import ArtifactRequest, SerialBridgeClient


def test_host_mission_and_jetson_result_cross_existing_protocol(tmp_path: Path) -> None:
    host_transport, jetson_transport = create_memory_link()
    jetson: ArtifactBridgeCore

    def jetson_event(event) -> None:
        if event.kind is BridgeEventKind.RECEIVED:
            jetson.acknowledge_applied(event.transfer_id)

    jetson = ArtifactBridgeCore(
        "jetson",
        SpoolManager(tmp_path / "jetson-spool"),
        jetson_transport,
        stored_ack_timeout=1.0,
        application_ack_timeout=1.0,
        on_event=jetson_event,
    )
    host = SerialBridgeClient(
        transport=host_transport,
        spool_dir=tmp_path / "host-spool",
        stored_ack_timeout=1.0,
        application_ack_timeout=1.0,
    )
    jetson.start()
    notices = []
    host.add_received_listener(notices.append)
    try:
        mission = tmp_path / "mission.json"
        mission.write_text(
            json.dumps({"mission_id": "mission-stage5", "mission_version": 1}),
            encoding="utf-8",
        )
        mission_request = ArtifactRequest(
            "mission_manifest",
            mission,
            "mission-stage5",
            1,
            hashlib.sha256(mission.read_bytes()).hexdigest(),
            100,
        )
        sent = host.send_artifact(mission_request).result(timeout=3.0)
        assert sent.success
        assert sent.frame_ack
        assert sent.remote_saved
        assert sent.application_ack
        assert jetson.completed_artifact(sent.transfer_id) is not None

        result_path = tmp_path / "semantic_result.json"
        result_path.write_text(
            json.dumps(
                {
                    "mission_id": "mission-stage5",
                    "base_map_version": 1,
                    "result_version": 2,
                    "victims": [],
                    "risks": [],
                    "routes": [],
                }
            ),
            encoding="utf-8",
        )
        metadata = ArtifactMetadata.from_file(
            result_path,
            artifact_type="semantic_result",
            mission_id="mission-stage5",
            artifact_version=2,
            sender="jetson",
            priority=200,
        )
        returned = []

        def send_result() -> None:
            returned.append(
                jetson.send_artifact(
                    result_path,
                    metadata,
                    require_application_ack=True,
                )
            )

        thread = threading.Thread(target=send_result)
        thread.start()
        deadline = threading.Event()
        for _ in range(300):
            if notices:
                break
            deadline.wait(0.01)
        assert notices
        notice = notices[0]
        assert notice.artifact_kind == "semantic_result"
        assert notice.local_path.read_bytes() == result_path.read_bytes()
        assert host.acknowledge_artifact(notice.transfer_id, True).result(timeout=1.0)
        thread.join(timeout=3.0)
        assert not thread.is_alive()
        assert returned and returned[0].success
        assert returned[0].application_ack
    finally:
        host.close()
        jetson.close()
