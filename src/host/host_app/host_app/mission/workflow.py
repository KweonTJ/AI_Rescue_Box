"""Asynchronous Host↔Bridge mission workflows and received-artifact loading."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import threading
import time
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from ..errors import ValidationError
from ..map_editor.preview import read_map_preview_metadata
from ..reconstruction import HostSemanticReconstructor, VersionGapError
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
UrgentCallback = Callable[[Mapping[str, object], ReceivedArtifactNotice], object]

TRANSFER_TIMEOUT_MARGIN_SECONDS = 30.0
TRANSFER_TIMEOUT_RATE_FLOOR_BYTES_PER_SECOND = 1024.0
TRANSFER_TIMEOUT_MAX_SECONDS = 900.0


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

    def _timeout_for_path(self, path: Path) -> float:
        """Return a bounded size-aware deadline for low-bandwidth UWB artifacts."""

        file_size = Path(path).stat().st_size
        estimated = (
            TRANSFER_TIMEOUT_MARGIN_SECONDS
            + float(file_size) / TRANSFER_TIMEOUT_RATE_FLOOR_BYTES_PER_SECOND
        )
        return max(
            self.transfer_timeout,
            min(TRANSFER_TIMEOUT_MAX_SECONDS, estimated),
        )

    def _wait_for_transfer(
        self,
        future: Future[SendResult],
        stage: str,
        transfer_id: Callable[[], str],
        *,
        timeout: float | None = None,
    ) -> SendResult:
        actual_timeout = self.transfer_timeout if timeout is None else float(timeout)
        try:
            return future.result(timeout=actual_timeout)
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
                f"{actual_timeout:g} seconds"
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

                base_future = self.bridge.send_artifact(base_request, base_feedback)
                base_result = self._wait_for_transfer(
                    base_future,
                    "base_map",
                    lambda: base_transfer_id[0],
                    timeout=self._timeout_for_path(base_map_path),
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
                    timeout=self._timeout_for_path(manifest_path),
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
                        send_future,
                        "approved_plan",
                        lambda: transfer_id[0],
                        timeout=self._timeout_for_path(plan_path),
                    )
                )
            except Exception as error:
                output.set_exception(error)

        threading.Thread(target=run, name="host-plan-send", daemon=True).start()
        return output


class ReceivedArtifactLoader:
    """Validate Bridge paths, reconstruct semantic deltas, then application-ACK."""

    def __init__(
        self,
        bridge: HostBridgeFacade,
        *,
        expected_mission_id: Callable[[], str | None] | None = None,
        expected_base_map_version: Callable[[], int | None] | None = None,
        on_semantic_result: SemanticCallback | None = None,
        on_map_preview: PreviewCallback | None = None,
        on_urgent_event: UrgentCallback | None = None,
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
        self.on_urgent_event = on_urgent_event
        self.on_error = on_error
        self.max_file_bytes = max_file_bytes
        self.apply_timeout = apply_timeout
        if ack_attempts < 1 or ack_retry_delay < 0:
            raise ValueError("ACK retry settings are invalid")
        self.ack_attempts = ack_attempts
        self.ack_retry_delay = ack_retry_delay
        self._reconstructor = HostSemanticReconstructor()
        self._reconstruction_lock = threading.RLock()
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

    @staticmethod
    def _read_object(path: Path) -> Mapping[str, object]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValidationError(f"artifact JSON을 읽을 수 없습니다: {error}") from error
        if not isinstance(value, Mapping):
            raise ValidationError("artifact JSON root must be an object")
        return value

    @staticmethod
    def _state_root(path: Path) -> Path | None:
        for parent in path.parents:
            if parent.name == "completed":
                root = parent.parent / "host_reconstruction"
                root.mkdir(parents=True, exist_ok=True)
                return root
        return None

    def _state_path(self, path: Path, mission_id: str, base_map_version: int) -> Path | None:
        root = self._state_root(path)
        if root is None:
            return None
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in mission_id)[:80]
        return root / f"{safe}.v{base_map_version}.semantic.json"

    @staticmethod
    def _atomic_state(path: Path, state: Mapping[str, object]) -> None:
        data = json.dumps(state, sort_keys=True, indent=2, ensure_ascii=False).encode("utf-8")
        part = path.with_name(f".{path.name}.{os.getpid()}.part")
        try:
            with part.open("wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(part, path)
        finally:
            part.unlink(missing_ok=True)

    def _seed_persisted_state(self, artifact_path: Path, mission_id: str) -> None:
        base_version = self.expected_base_map_version()
        if base_version is None:
            return
        current = self._reconstructor.current(mission_id, int(base_version))
        if current is not None:
            return
        state_path = self._state_path(artifact_path, mission_id, int(base_version))
        if state_path is None or not state_path.is_file():
            return
        value = self._read_object(state_path)
        try:
            self._reconstructor.apply_semantic_result(value)
        except Exception as error:
            raise ValidationError(f"저장된 Host reconstruction state가 손상되었습니다: {error}") from error

    def _persist_state(self, artifact_path: Path, state: Mapping[str, object]) -> None:
        base_version = int(state.get("base_map_version", 0))
        mission_id = str(state.get("mission_id", ""))
        if not mission_id or base_version < 1:
            return
        state_path = self._state_path(artifact_path, mission_id, base_version)
        if state_path is not None:
            self._atomic_state(state_path, state)

    @staticmethod
    def _review_owner(callback: SemanticCallback | None) -> Any | None:
        return getattr(callback, "__self__", None) if callback is not None else None

    def _preserve_review_overlay(self, semantic: SemanticResult) -> None:
        """Rebase the previous Host review overlay onto a newly reconstructed version.

        ReviewSession intentionally keeps source semantics and operator edits separate.
        The Host API owns those sessions; this adapter only copies the public edit
        overlay after its normal semantic callback creates the new version. Missing
        source IDs are preserved as explicit conflicts rather than silently dropped.
        """

        owner = self._review_owner(self.on_semantic_result)
        reviews = getattr(owner, "_reviews", None)
        revisions = getattr(owner, "_review_revisions", None)
        lock = getattr(owner, "_lock", None)
        events = getattr(owner, "events", None)
        if not isinstance(reviews, dict) or not isinstance(revisions, dict) or lock is None:
            return
        mission_version = int(semantic.to_dict().get("base_map_version", 0))
        new_version = int(semantic.result_version)
        if mission_version < 1 or new_version <= 1:
            return
        previous_key = (semantic.mission_id, mission_version, new_version - 1)
        new_key = (semantic.mission_id, mission_version, new_version)
        with lock:
            previous = reviews.get(previous_key)
            current = reviews.get(new_key)
            if previous is None or current is None:
                return
            edits = previous.host_edits
            current._edits = copy.deepcopy(edits)
            current._undo = []
            current._redo = []
            current._final_approved = None
            revisions[new_key] = int(revisions.get(previous_key, 0)) + 1
            conflicts = self._review_conflicts(semantic.to_dict(), edits)
        if events is not None:
            events.publish(
                "review.rebased",
                {
                    "mission_id": semantic.mission_id,
                    "mission_version": mission_version,
                    "from_result_version": new_version - 1,
                    "result_version": new_version,
                    "conflict_count": len(conflicts),
                },
            )
            if conflicts:
                events.publish(
                    "review.conflict",
                    {
                        "mission_id": semantic.mission_id,
                        "mission_version": mission_version,
                        "result_version": new_version,
                        "conflicts": conflicts,
                    },
                )

    @staticmethod
    def _review_conflicts(
        semantic: Mapping[str, Any], edits: Mapping[str, Any]
    ) -> list[Mapping[str, str]]:
        def ids(layer: str, keys: tuple[str, ...]) -> set[str]:
            result: set[str] = set()
            values = semantic.get(layer, [])
            if not isinstance(values, list):
                return result
            for item in values:
                if not isinstance(item, Mapping):
                    continue
                for key in keys:
                    if item.get(key) not in {None, ""}:
                        result.add(str(item[key]))
                        break
            return result

        victim_ids = ids("victim_candidates", ("detection_id", "victim_id", "id")) | ids(
            "confirmed_victims", ("detection_id", "victim_id", "id")
        )
        risk_ids = ids("risk_zones", ("risk_id", "id"))
        route_ids = ids("entry_routes", ("route_id", "id"))
        conflicts: list[Mapping[str, str]] = []
        for edit_key in ("victim_status", "victim_priorities", "victim_modifications"):
            values = edits.get(edit_key, {})
            if isinstance(values, Mapping):
                for identity in values:
                    if str(identity) not in victim_ids:
                        conflicts.append({"kind": edit_key, "id": str(identity)})
        risk_modifications = edits.get("risk_modifications", {})
        if isinstance(risk_modifications, Mapping):
            for identity in risk_modifications:
                if str(identity) not in risk_ids:
                    conflicts.append({"kind": "risk_modification", "id": str(identity)})
        cleared = edits.get("cleared_risk_ids", [])
        if isinstance(cleared, list):
            for identity in cleared:
                if str(identity) not in risk_ids:
                    conflicts.append({"kind": "cleared_risk", "id": str(identity)})
        route_approvals = edits.get("route_approvals", {})
        if isinstance(route_approvals, Mapping):
            for identity in route_approvals:
                if str(identity) not in route_ids:
                    conflicts.append({"kind": "route_approval", "id": str(identity)})
        return conflicts

    def _publish_urgent_default(
        self, event: Mapping[str, object], notice: ReceivedArtifactNotice
    ) -> None:
        owner = self._review_owner(self.on_semantic_result)
        events = getattr(owner, "events", None)
        if events is not None:
            events.publish(
                "urgent_event.received",
                {
                    "mission_id": notice.mission_id,
                    "artifact_version": notice.artifact_version,
                    "transfer_id": notice.transfer_id,
                    "event_id": event.get("event_id"),
                    "event_type": event.get("event_type"),
                    "priority": event.get("priority"),
                    "payload": copy.deepcopy(event.get("payload", {})),
                },
            )

    def _received(self, notice: ReceivedArtifactNotice) -> None:
        threading.Thread(
            target=self._load,
            args=(notice,),
            name="host-artifact-loader",
            daemon=True,
        ).start()

    def _apply_semantic_callback(
        self, semantic: SemanticResult, notice: ReceivedArtifactNotice
    ) -> None:
        if self.on_semantic_result is None:
            return
        self._await_application(self.on_semantic_result(semantic, notice))
        self._preserve_review_overlay(semantic)

    def _load(self, notice: ReceivedArtifactNotice) -> None:
        try:
            path = self._validate_file(notice)
            if notice.artifact_kind == "semantic_result":
                value = self._read_object(path)
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
                with self._reconstruction_lock:
                    self._seed_persisted_state(path, semantic.mission_id)
                    outcome = self._reconstructor.apply_semantic_result(semantic.to_dict())
                    state = outcome.state
                    self._persist_state(path, state)
                if outcome.applied:
                    self._apply_semantic_callback(SemanticResult(state), notice)
            elif notice.artifact_kind == "map_delta":
                delta = self._read_object(path)
                self._validate_map_delta(delta, notice)
                with self._reconstruction_lock:
                    self._seed_persisted_state(path, notice.mission_id)
                    try:
                        outcome = self._reconstructor.apply_delta(delta)
                    except VersionGapError as error:
                        raise ValidationError(str(error)) from error
                    state = outcome.state
                    if outcome.applied:
                        self._persist_state(path, state)
                # Duplicate/stale retransmissions are application-idempotent and
                # ACKed without reapplying. A newly reconstructed state flows
                # through the existing semantic-result callback so WebSocket,
                # review, storage and UI behavior stay intact.
                if outcome.applied:
                    self._apply_semantic_callback(SemanticResult(state), notice)
            elif notice.artifact_kind == "urgent_event":
                event = self._read_object(path)
                self._validate_urgent_event(event, notice)
                if self.on_urgent_event is not None:
                    self._await_application(self.on_urgent_event(event, notice))
                else:
                    self._publish_urgent_default(event, notice)
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

    def _validate_map_delta(
        self, value: Mapping[str, object], notice: ReceivedArtifactNotice
    ) -> None:
        if value.get("schema_version") != "1.0":
            raise ValidationError("unsupported map_delta schema_version")
        if value.get("mission_id") != notice.mission_id:
            raise ValidationError("map_delta mission_id differs from transfer metadata")
        result_version = value.get("result_version")
        base_version = value.get("base_result_version")
        artifact_version = value.get("artifact_version")
        if any(
            isinstance(item, bool) or not isinstance(item, int)
            for item in (result_version, base_version, artifact_version)
        ):
            raise ValidationError("map_delta versions must be integers")
        assert isinstance(result_version, int)
        assert isinstance(base_version, int)
        assert isinstance(artifact_version, int)
        if result_version != base_version + 1 or artifact_version != result_version:
            raise ValidationError("map_delta versions are not contiguous")
        if result_version != notice.artifact_version:
            raise ValidationError("map_delta version differs from transfer metadata")
        if value.get("coordinate_frame") != "mission_map":
            raise ValidationError("map_delta coordinate_frame must be mission_map")
        if not isinstance(value.get("semantic_updates", {}), Mapping):
            raise ValidationError("map_delta semantic_updates must be an object")

    @staticmethod
    def _validate_urgent_event(
        value: Mapping[str, object], notice: ReceivedArtifactNotice
    ) -> None:
        allowed = {"new_victim", "critical_risk", "route_blocked", "mission_error"}
        if value.get("schema_version") != "1.0":
            raise ValidationError("unsupported urgent_event schema_version")
        if value.get("mission_id") != notice.mission_id:
            raise ValidationError("urgent_event mission_id differs from transfer metadata")
        if value.get("event_type") not in allowed or not value.get("event_id"):
            raise ValidationError("urgent_event identity/type is invalid")
        if value.get("artifact_version") != notice.artifact_version:
            raise ValidationError("urgent_event version differs from transfer metadata")
        if value.get("coordinate_frame") != "mission_map":
            raise ValidationError("urgent_event coordinate_frame must be mission_map")
        if not isinstance(value.get("payload"), Mapping):
            raise ValidationError("urgent_event payload must be an object")

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
