from __future__ import annotations

import hashlib
import io
import json
import sys
import threading
import time
from concurrent.futures import Future
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src" / "host" / "host_app"))
sys.path.insert(0, str(REPO_ROOT / "src" / "d_slam" / "jetson_app"))

from ai_rescue_uwb_common.bridge import ArtifactBridgeCore, BridgeEventKind
from ai_rescue_uwb_common.protocol import ArtifactMetadata
from ai_rescue_uwb_common.spool import SpoolManager as UwbSpoolManager
from ai_rescue_uwb_common.transport import create_memory_link
from host_app.api.service import HostApiService
from host_app.ros_client.bridge_client import (
    ArtifactRequest,
    BridgeClient,
    BridgeConnectionState,
    BridgeStatus,
    ReceivedArtifactNotice,
    SendFeedback,
    SendResult,
)
from jetson_app.api.service import JetsonApiService
from jetson_app.mission import MissionManager
from jetson_app.mission.application import MissionApplicationService
from jetson_app.stage2_mock import Stage2MockGenerator
from runtime.mission_artifacts import ReceivedMissionArtifact
from runtime.stage2 import JetsonStage2Runtime


class CoreHostBridgeClient(BridgeClient):
    def __init__(self, core: ArtifactBridgeCore) -> None:
        self.core = core
        self._received = []
        self._status = []

    def status(self) -> BridgeStatus:
        return BridgeStatus(
            state=BridgeConnectionState.READY,
            bridge_running=True,
            serial_connected=True,
            peer_connected=True,
        )

    def add_received_listener(self, callback):
        if callback not in self._received:
            self._received.append(callback)

    def remove_received_listener(self, callback):
        if callback in self._received:
            self._received.remove(callback)

    def add_status_listener(self, callback):
        if callback not in self._status:
            self._status.append(callback)

    def remove_status_listener(self, callback):
        if callback in self._status:
            self._status.remove(callback)

    def on_core_event(self, event) -> None:
        if event.kind is not BridgeEventKind.RECEIVED or event.artifact is None:
            return
        artifact = event.artifact
        notice = ReceivedArtifactNotice(
            transfer_id=artifact.transfer_id,
            artifact_kind=artifact.metadata.artifact_type,
            mission_id=artifact.metadata.mission_id,
            artifact_version=artifact.metadata.artifact_version,
            local_path=artifact.path.resolve(),
            file_size=artifact.metadata.file_size,
            sha256=artifact.metadata.sha256,
            sender=artifact.metadata.sender,
            received_at="2026-08-20T00:00:00Z",
        )
        for callback in tuple(self._received):
            callback(notice)

    def send_artifact(self, request: ArtifactRequest, feedback=None) -> Future[SendResult]:
        output: Future[SendResult] = Future()

        def run() -> None:
            try:
                metadata = ArtifactMetadata.from_file(
                    request.local_path,
                    artifact_type=request.artifact_kind,
                    mission_id=request.mission_id,
                    artifact_version=request.artifact_version,
                    sender="host",
                    priority=request.priority,
                )

                def progress(event) -> None:
                    if feedback is None:
                        return
                    feedback(
                        SendFeedback(
                            transfer_id=event.transfer_id,
                            stage=event.message or self.core.snapshot().transfer_state,
                            total_chunks=event.total_chunks,
                            completed_chunks=event.completed_chunks,
                            progress=(event.completed_chunks / event.total_chunks if event.total_chunks else 0.0),
                            retry_count=event.retries,
                            bytes_sent=event.bytes_sent,
                        )
                    )

                result = self.core.send_artifact(
                    request.local_path,
                    metadata,
                    require_application_ack=request.artifact_kind != "base_map",
                    progress=progress,
                )
                output.set_result(
                    SendResult(
                        result.success,
                        result.transfer_id,
                        result.uwb_frame_ack,
                        result.peer_saved,
                        result.application_ack,
                        result.error_code,
                        result.error_message,
                    )
                )
            except Exception as error:
                output.set_exception(error)

        threading.Thread(target=run, daemon=True).start()
        return output

    def acknowledge_artifact(self, transfer_id: str, applied: bool, error_message: str = "") -> Future[bool]:
        future: Future[bool] = Future()
        try:
            if applied:
                self.core.acknowledge_applied(transfer_id)
            else:
                self.core.reject_applied(transfer_id, error_message)
            future.set_result(True)
        except Exception as error:
            future.set_exception(error)
        return future


class CoreJetsonPort:
    def __init__(self, core: ArtifactBridgeCore, trace: list[str]) -> None:
        self.core = core
        self.trace = trace

    def acknowledge(self, transfer_id: str, *, applied: bool, error_message: str = "") -> None:
        self.trace.append(f"ack:{transfer_id}:{applied}")
        if applied:
            self.core.acknowledge_applied(transfer_id)
        else:
            self.core.reject_applied(transfer_id, error_message)

    def send_artifact(self, path: Path, *, artifact_type: str, mission_id: str, artifact_version: int, priority: int = 100):
        metadata = ArtifactMetadata.from_file(
            path,
            artifact_type=artifact_type,
            mission_id=mission_id,
            artifact_version=artifact_version,
            sender="jetson",
            priority=priority,
        )
        result = self.core.send_artifact(path, metadata, require_application_ack=True)
        assert result.success, result.error_message
        return {
            "success": result.success,
            "transfer_id": result.transfer_id,
            "frame_ack": result.uwb_frame_ack,
            "peer_stored_ack": result.peer_saved,
            "application_applied_ack": result.application_ack,
        }


class RecordingApplication:
    def __init__(self, service: MissionApplicationService, trace: list[str]) -> None:
        self.service = service
        self.trace = trace

    def load_mission(self, **kwargs):
        self.trace.append("load_mission")
        return self.service.load_mission(**kwargs)

    def apply_approved_plan(self, **kwargs):
        self.trace.append("apply_approved_plan")
        return self.service.apply_approved_plan(**kwargs)


def _operation(service: HostApiService, value: dict, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    current = value
    while current["state"] == "running" and time.time() < deadline:
        time.sleep(0.02)
        current = service.get_operation(current["operation_id"])
    assert current["state"] == "succeeded", current
    return current


def _png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (8, 6), "white").save(output, format="PNG")
    return output.getvalue()


def test_stage2_round_trip_uses_real_protocol_runtime_and_application_ack(tmp_path: Path) -> None:
    host_transport, jetson_transport = create_memory_link()
    host_client_holder = {}
    jetson_runtime_holder = {}

    def host_event(event):
        client = host_client_holder.get("client")
        if client is not None:
            client.on_core_event(event)

    def jetson_event(event):
        runtime = jetson_runtime_holder.get("runtime")
        if runtime is None or event.kind is not BridgeEventKind.RECEIVED or event.artifact is None:
            return
        completed = event.artifact
        runtime.handle_received(
            ReceivedMissionArtifact(
                transfer_id=completed.transfer_id,
                artifact_type=completed.metadata.artifact_type,
                mission_id=completed.metadata.mission_id,
                artifact_version=completed.metadata.artifact_version,
                local_file_path=completed.path,
                sha256=completed.metadata.sha256,
            )
        )

    host_core = ArtifactBridgeCore(
        "host", UwbSpoolManager(tmp_path / "host_uwb"), host_transport,
        stored_ack_timeout=1.0, application_ack_timeout=2.0, on_event=host_event,
    )
    jetson_core = ArtifactBridgeCore(
        "jetson", UwbSpoolManager(tmp_path / "jetson_uwb"), jetson_transport,
        stored_ack_timeout=1.0, application_ack_timeout=2.0, on_event=jetson_event,
    )
    client = CoreHostBridgeClient(host_core)
    host_client_holder["client"] = client

    from host_app.ros_client.bridge_client import HostBridgeFacade
    host_service = HostApiService(tmp_path / "host_data", bridge=HostBridgeFacade(client), transfer_timeout=3.0)
    manager = MissionManager(tmp_path / "jetson_data" / "missions")
    trace: list[str] = []
    jetson_port = CoreJetsonPort(jetson_core, trace)
    runtime = JetsonStage2Runtime(
        RecordingApplication(MissionApplicationService(manager), trace),
        jetson_port,
        jetson_port,
    )
    jetson_runtime_holder["runtime"] = runtime
    host_core.start(); jetson_core.start()
    try:
        uploaded = host_service.upload_map("base.png", _png_bytes())
        manifest = host_service.create_mission(
            {
                "map_id": uploaded["map_id"],
                "mission_id": "stage2-e2e",
                "mission_version": 1,
                "mission_name": "Stage 2 E2E",
                "robot_start_image": {"x": 1.0, "y": 1.0},
                "meters_per_pixel": 0.25,
                "initial_yaw": 0.0,
                "entrances": [{"x": 0.0, "y": 0.0}],
                "available_teams": 1,
                "available_rescuers": 2,
            }
        )
        sent = _operation(host_service, host_service.send_mission("stage2-e2e", 1))
        assert sent["result"]["base_map"]["remote_saved"] is True
        assert sent["result"]["base_map"]["application_ack"] is False
        assert sent["result"]["mission_manifest"]["application_ack"] is True
        # UWB completion now means verified + STORED. It must not switch the
        # Jetson ACTIVE mission behind the Tablet operator's back.
        assert manager.current_mission_ref() is None
        assert trace.index("load_mission") < next(
            index for index, item in enumerate(trace) if item.endswith(":True")
        )

        tablet_service = JetsonApiService(
            MissionManager(tmp_path / "jetson_data" / "missions"), mode="mock"
        )
        assert tablet_service.list_missions()[0]["active"] is False
        tablet_service.select_mission("stage2-e2e", 1)
        assert manager.current_mission_ref() == ("stage2-e2e", 1)
        tablet_mission = tablet_service.current_mission()
        assert tablet_mission["mission_id"] == manifest["mission_id"]
        assert tablet_mission["mission_version"] == manifest["mission_version"]
        assert hashlib.sha256(manager.load_mission("stage2-e2e", 1).base_map_path.read_bytes()).hexdigest() == manifest["base_map"]["sha256"]

        mock = Stage2MockGenerator(manager).generate()
        result_payload = json.loads(mock.semantic_result_path.read_text(encoding="utf-8"))
        assert result_payload["analysis_mode"] == "mock"
        assert result_payload["coordinate_frame"] == "mission_map"
        assert result_payload["mission_id"] == "stage2-e2e"
        runtime.return_analysis(mock.semantic_result_path, mock.map_preview_path)
        stored_result = host_service.get_result("stage2-e2e", 1, mock.result_version)
        assert stored_result["analysis_mode"] == "mock"
        assert host_service.preview_metadata("stage2-e2e", 1, mock.result_version)["mission_id"] == "stage2-e2e"

        plan = host_service.build_approved_plan("stage2-e2e", 1, mock.result_version, 1)
        assert plan["mission_id"] == "stage2-e2e"
        _operation(host_service, host_service.send_approved_plan("stage2-e2e", 1, mock.result_version, 1))
        applied_plan = json.loads((manager.mission_directory("stage2-e2e", 1) / "approved_plan.json").read_text(encoding="utf-8"))
        assert applied_plan["mission_id"] == "stage2-e2e"
        assert applied_plan["base_result_version"] == mock.result_version
        assert applied_plan["approved_plan_version"] == 1
        assert "apply_approved_plan" in trace
    finally:
        host_service.close(); host_core.close(); jetson_core.close()


def test_stage2_rejects_incomplete_or_mismatched_artifacts(tmp_path: Path) -> None:
    class Ack:
        def __init__(self): self.items=[]
        def acknowledge(self, transfer_id, *, applied, error_message=""): self.items.append((transfer_id, applied, error_message))
    class App:
        def __init__(self): self.loads=0; self.plans=0
        def load_mission(self, **kwargs): self.loads += 1; raise AssertionError("must not apply invalid mission")
        def apply_approved_plan(self, **kwargs): self.plans += 1; raise AssertionError("must not apply invalid plan")
    ack=Ack(); app=App(); runtime=JetsonStage2Runtime(app, ack)
    base=tmp_path/"base.png"; Image.new("RGB",(4,3),"white").save(base); digest=hashlib.sha256(base.read_bytes()).hexdigest()
    manifest=tmp_path/"mission.json"; manifest.write_text(json.dumps({"mission_id":"m1","mission_version":2,"artifact_version":2,"base_map_sha256":digest}),encoding="utf-8")
    manifest_sha=hashlib.sha256(manifest.read_bytes()).hexdigest()

    assert runtime.handle_received(ReceivedMissionArtifact("manifest-only","mission_manifest","m1",2,manifest,manifest_sha)) == "pending"
    assert app.loads == 0
    assert ack.items == []

    bad_base=ReceivedMissionArtifact("base-bad","base_map","m1",2,base,"0"*64)
    assert runtime.handle_received(bad_base) == "rejected"
    assert app.loads == 0
    assert ack.items[-1][1] is False

    mismatch_manifest=tmp_path/"mission-version-mismatch.json"
    mismatch_manifest.write_text(
        json.dumps({
            "mission_id":"m-version",
            "mission_version":3,
            "artifact_version":3,
            "base_map_sha256":digest,
        }),
        encoding="utf-8",
    )
    mismatch_sha=hashlib.sha256(mismatch_manifest.read_bytes()).hexdigest()
    assert runtime.handle_received(
        ReceivedMissionArtifact(
            "manifest-version-mismatch",
            "mission_manifest",
            "m-version",
            2,
            mismatch_manifest,
            mismatch_sha,
        )
    ) == "pending"
    assert runtime.handle_received(
        ReceivedMissionArtifact(
            "base-version-mismatch",
            "base_map",
            "m-version",
            2,
            base,
            digest,
        )
    ) == "rejected"
    assert app.loads == 0
    assert ack.items[-1][1] is False

    plan=tmp_path/"plan.json"; plan.write_text(json.dumps({"mission_id":"other","mission_version":2,"approved_plan_version":1,"artifact_version":1}),encoding="utf-8")
    plan_sha=hashlib.sha256(plan.read_bytes()).hexdigest()
    assert runtime.handle_received(ReceivedMissionArtifact("plan-wrong","approved_plan","m1",1,plan,plan_sha)) == "rejected"
    assert app.plans == 0
    assert ack.items[-1][1] is False
