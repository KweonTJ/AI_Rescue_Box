"""Asynchronous Host↔Bridge mission workflows and received-artifact loading."""

from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..errors import ValidationError
from ..map_editor.preview import read_map_preview_metadata
from ..ros_client.bridge_client import (
    ArtifactRequest,
    HostBridgeFacade,
    ReceivedArtifactNotice,
    SendFeedback,
    SendResult,
)
from .models import MissionManifest, SemanticResult
from .review import ApprovedPlan


ProgressCallback = Callable[[str, SendFeedback], None]
SemanticCallback = Callable[[SemanticResult, ReceivedArtifactNotice], object]
PreviewCallback = Callable[[Path, ReceivedArtifactNotice], object]
ErrorCallback = Callable[[str, ReceivedArtifactNotice], None]


def map_preview_base_map_version(path: Path) -> int:
    return read_map_preview_metadata(path).base_map_version


@dataclass(frozen=True)
class MissionSendResult:
    success: bool
    base_map: SendResult
    mission_manifest: SendResult | None

    @property
    def error_message(self) -> str:
        if not self.base_map.success:
            return self.base_map.error_message
        if self.mission_manifest is not None and not self.mission_manifest.success:
            return self.mission_manifest.error_message
        return ""


def _request(
    kind: str, path: Path, mission_id: str, version: int, priority: int
) -> ArtifactRequest:
    path = Path(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return ArtifactRequest(kind, path, mission_id, version, digest, priority)


class HostTransferWorkflow:
    def __init__(
        self, bridge: HostBridgeFacade, *, transfer_timeout: float = 45.0
    ):
        try:
            parsed_timeout = float(transfer_timeout)
        except (TypeError, ValueError) as error:
            raise ValueError("transfer_timeout must be positive and finite") from error
        if not math.isfinite(parsed_timeout) or parsed_timeout <= 0:
            raise ValueError("transfer_timeout must be positive and finite")
        self.bridge = bridge
        self.transfer_timeout = parsed_timeout

    def _wait_for_transfer(
        self,
        future: Future[SendResult],
        stage: str,
        transfer_id: Callable[[], str],
    ) -> SendResult:
        try:
            return future.result(timeout=self.transfer_timeout)
        except FutureTimeoutError as error:
            future.cancel()
            known_transfer_id = transfer_id()
            if known_transfer_id:
                try:
                    self.bridge.cancel_transfer(known_transfer_id)
                except Exception:
                    pass
            raise TimeoutError(
                f"{stage} transfer did not finish within "
                f"{self.transfer_timeout:g} seconds"
            ) from error

    def send_initial_mission(
        self,
        manifest: MissionManifest,
        base_map_path: Path,
        manifest_path: Path,
        progress: ProgressCallback | None = None,
    ) -> Future[MissionSendResult]:
        output: Future[MissionSendResult] = Future()

        def run() -> None:
            try:
                base_request = _request(
                    "base_map",
                    base_map_path,
                    manifest.mission_id,
                    manifest.mission_version,
                    priority=10,
                )
                base_transfer_id = [""]

                def base_feedback(item: SendFeedback) -> None:
                    base_transfer_id[0] = item.transfer_id
                    if progress is not None:
                        progress("base_map", item)

                base_future = self.bridge.send_artifact(
                    base_request, base_feedback
                )
                base_result = self._wait_for_transfer(
                    base_future, "base_map", lambda: base_transfer_id[0]
                )
                if not base_result.success:
                    output.set_result(MissionSendResult(False, base_result, None))
                    return
                manifest_request = _request(
                    "mission_manifest",
                    manifest_path,
                    manifest.mission_id,
                    manifest.mission_version,
                    priority=9,
                )
                manifest_transfer_id = [""]

                def manifest_feedback(item: SendFeedback) -> None:
                    manifest_transfer_id[0] = item.transfer_id
                    if progress is not None:
                        progress("mission_manifest", item)

                manifest_future = self.bridge.send_artifact(
                    manifest_request, manifest_feedback
                )
                manifest_result = self._wait_for_transfer(
                    manifest_future,
                    "mission_manifest",
                    lambda: manifest_transfer_id[0],
                )
                output.set_result(
                    MissionSendResult(
                        manifest_result.success, base_result, manifest_result
                    )
                )
            except Exception as error:
                output.set_exception(error)

        threading.Thread(target=run, name="host-mission-send", daemon=True).start()
        return output

    def send_approved_plan(
        self,
        plan: ApprovedPlan,
        plan_path: Path,
        progress: ProgressCallback | None = None,
    ) -> Future[SendResult]:
        output: Future[SendResult] = Future()

        def run() -> None:
            try:
                request = _request(
                    "approved_plan",
                    plan_path,
                    plan.mission_id,
                    plan.approved_plan_version,
                    priority=10,
                )
                transfer_id = [""]

                def feedback(item: SendFeedback) -> None:
                    transfer_id[0] = item.transfer_id
                    if progress is not None:
                        progress("approved_plan", item)

                send_future = self.bridge.send_artifact(request, feedback)
                output.set_result(
                    self._wait_for_transfer(
                        send_future, "approved_plan", lambda: transfer_id[0]
                    )
                )
            except Exception as error:
                output.set_exception(error)

        threading.Thread(target=run, name="host-plan-send", daemon=True).start()
        return output


class ReceivedArtifactLoader:
    """Validate Bridge paths again, load supported results, then application-ACK."""

    def __init__(
        self,
        bridge: HostBridgeFacade,
        *,
        expected_mission_id: Callable[[], str | None] | None = None,
        expected_base_map_version: Callable[[], int | None] | None = None,
        on_semantic_result: SemanticCallback | None = None,
        on_map_preview: PreviewCallback | None = None,
        on_error: ErrorCallback | None = None,
        max_file_bytes: int = 10 * 1024 * 1024,
        apply_timeout: float = 30.0,
        ack_attempts: int = 3,
        ack_retry_delay: float = 0.1,
    ) -> None:
        self.bridge = bridge
        self.expected_mission_id = expected_mission_id or (lambda: None)
        self.expected_base_map_version = expected_base_map_version or (lambda: None)
        self.on_semantic_result = on_semantic_result
        self.on_map_preview = on_map_preview
        self.on_error = on_error
        self.max_file_bytes = max_file_bytes
        self.apply_timeout = apply_timeout
        if ack_attempts < 1 or ack_retry_delay < 0:
            raise ValueError("ACK retry settings are invalid")
        self.ack_attempts = ack_attempts
        self.ack_retry_delay = ack_retry_delay
        self.bridge.add_received_listener(self._received)

    def close(self) -> None:
        self.bridge.remove_received_listener(self._received)

    def _validate_file(self, notice: ReceivedArtifactNotice) -> Path:
        path = notice.local_path.expanduser()
        if not path.is_absolute() or not path.is_file() or path.is_symlink():
            raise ValidationError("Bridge가 전달한 artifact 경로가 안전하지 않습니다.")
        size = path.stat().st_size
        if size < 1 or size > self.max_file_bytes or size != notice.file_size:
            raise ValidationError("수신 artifact 크기가 metadata와 다릅니다.")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != notice.sha256:
            raise ValidationError("수신 artifact SHA-256이 metadata와 다릅니다.")
        active_mission = self.expected_mission_id()
        if active_mission is not None and notice.mission_id != active_mission:
            raise ValidationError("수신 artifact mission_id가 현재 임무와 다릅니다.")
        return path

    def _received(self, notice: ReceivedArtifactNotice) -> None:
        threading.Thread(
            target=self._load,
            args=(notice,),
            name="host-artifact-loader",
            daemon=True,
        ).start()

    def _load(self, notice: ReceivedArtifactNotice) -> None:
        try:
            path = self._validate_file(notice)
            if notice.artifact_kind == "semantic_result":
                with path.open("r", encoding="utf-8") as source:
                    value = json.load(source)
                semantic = SemanticResult(value)
                if semantic.mission_id != notice.mission_id:
                    raise ValidationError(
                        "semantic_result 내용과 전송 metadata의 mission_id가 다릅니다."
                    )
                if semantic.result_version != notice.artifact_version:
                    raise ValidationError(
                        "semantic_result 내용과 전송 metadata의 버전이 다릅니다."
                    )
                active_base_map_version = self.expected_base_map_version()
                if (
                    active_base_map_version is not None
                    and int(semantic.to_dict()["base_map_version"])
                    != active_base_map_version
                ):
                    raise ValidationError(
                        "semantic_result가 현재 mission/base-map 버전을 기준으로 하지 않았습니다."
                    )
                if self.on_semantic_result is not None:
                    self._await_application(
                        self.on_semantic_result(semantic, notice)
                    )
            elif notice.artifact_kind == "map_preview":
                preview_metadata = read_map_preview_metadata(path)
                if preview_metadata.mission_id != notice.mission_id:
                    raise ValidationError(
                        "map_preview PNG와 전송 metadata의 mission_id가 다릅니다."
                    )
                if preview_metadata.artifact_version != notice.artifact_version:
                    raise ValidationError(
                        "map_preview PNG와 전송 metadata의 버전이 다릅니다."
                    )
                active_base_map_version = self.expected_base_map_version()
                if (
                    active_base_map_version is not None
                    and preview_metadata.base_map_version != active_base_map_version
                ):
                    raise ValidationError(
                        "map_preview가 현재 mission/base-map 버전을 기준으로 하지 않았습니다."
                    )
                if self.on_map_preview is not None:
                    self._await_application(self.on_map_preview(path, notice))
            else:
                raise ValidationError(
                    f"Host 앱이 적용할 수 없는 artifact 종류입니다: {notice.artifact_kind}"
                )
        except Exception as error:
            try:
                self._send_application_ack(notice.transfer_id, False, str(error))
            except Exception as ack_error:
                error = ValidationError(
                    f"{error}; application NACK 전달 실패: {ack_error}"
                )
            if self.on_error is not None:
                self.on_error(str(error), notice)
            return
        try:
            self._send_application_ack(notice.transfer_id, True, "")
        except Exception as error:
            if self.on_error is not None:
                self.on_error(f"application ACK 전달 실패: {error}", notice)

    def _send_application_ack(
        self, transfer_id: str, applied: bool, error_message: str
    ) -> None:
        last_error: Exception | None = None
        for attempt in range(self.ack_attempts):
            try:
                accepted = self.bridge.acknowledge_artifact(
                    transfer_id, applied, error_message
                ).result(timeout=self.apply_timeout)
                if accepted:
                    return
                last_error = RuntimeError("Bridge가 application ACK 요청을 거절했습니다.")
            except Exception as error:
                last_error = error
            if attempt + 1 < self.ack_attempts and self.ack_retry_delay:
                time.sleep(self.ack_retry_delay)
        assert last_error is not None
        raise last_error

    def _await_application(self, outcome: object) -> None:
        if isinstance(outcome, Future):
            outcome = outcome.result(timeout=self.apply_timeout)
        if outcome is False:
            raise ValidationError("Host 앱이 artifact 적용을 거절했습니다.")
