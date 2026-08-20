"""Continuous semantic-update extension for the Stage 4 Jetson API."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Mapping

from ..semantic_updates import SemanticChangeDetector
from ..storage import atomic_write_json
from .service import ApiUnavailableError
from .stage4_service import Stage4JetsonApiService


class ContinuousStage4JetsonApiService(Stage4JetsonApiService):
    """Run bounded semantic analysis while an explicitly selected mission is ACTIVE."""

    def __init__(self, *args: Any, semantic_poll_seconds: float | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        configured = semantic_poll_seconds
        if configured is None:
            configured = float(os.environ.get("AI_RESCUE_SEMANTIC_POLL_SECONDS", "2.0"))
        self.semantic_poll_seconds = max(0.2, float(configured))
        self._semantic_detector = SemanticChangeDetector()
        self._semantic_stop = threading.Event()
        self._semantic_wake = threading.Event()
        self._semantic_thread: threading.Thread | None = None
        self._semantic_lock = threading.RLock()
        self._needs_full_resync = False

    def list_missions(self):
        selected = self._selected_ref()
        values = []
        for mission_id, version in self.manager.list_missions():
            detail = self.mission_detail(mission_id, version)
            verification = detail.get("verification", {})
            manifest = detail.get("manifest", {})
            values.append({
                "mission_id": mission_id,
                "mission_version": version,
                "mission_name": manifest.get("mission_name", mission_id),
                "active": selected == (mission_id, version),
                "verified": verification.get("status") == "verified",
                "verification_status": verification.get("status", "unknown"),
                "verified_at": verification.get("verified_at"),
                "received_at": verification.get("received_at", verification.get("verified_at")),
                "base_map": detail.get("base_map", {}),
            })
        return values

    def mission_detail(self, mission_id, mission_version):
        value = dict(super().mission_detail(mission_id, mission_version))
        applied = self.manager.load_mission(mission_id, mission_version)
        try:
            verification = json.loads(applied.verification_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            verification = {"status": "unknown"}
        value["verification"] = verification
        value["active"] = self._selected_ref() == (mission_id, mission_version)
        return value

    def _reset_for_mission(self, selected: tuple[str, int]) -> None:
        before = self._runtime_mission_ref
        super()._reset_for_mission(selected)
        if before != selected:
            with self._semantic_lock:
                self._semantic_detector.reset()
                self._needs_full_resync = False
            self.events.publish(
                "semantic_monitor.reset",
                {"mission_id": selected[0], "mission_version": selected[1]},
            )
            self._semantic_wake.set()

    def select_mission(self, mission_id, mission_version):
        value = super().select_mission(mission_id, mission_version)
        self._semantic_wake.set()
        return value

    def start_semantic_monitor(self) -> None:
        with self._semantic_lock:
            if self._semantic_thread is not None and self._semantic_thread.is_alive():
                return
            self._semantic_stop.clear()
            self._semantic_thread = threading.Thread(
                target=self._semantic_loop,
                name="jetson-semantic-update-monitor",
                daemon=True,
            )
            self._semantic_thread.start()

    def stop_semantic_monitor(self) -> None:
        self._semantic_stop.set()
        self._semantic_wake.set()
        thread = self._semantic_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(1.0, self.semantic_poll_seconds * 2.0))
        self._semantic_thread = None

    def _semantic_loop(self) -> None:
        while not self._semantic_stop.is_set():
            self._semantic_wake.wait(self.semantic_poll_seconds)
            self._semantic_wake.clear()
            if self._semantic_stop.is_set():
                return
            try:
                self.semantic_update_tick()
            except Exception as error:
                self.events.publish(
                    "semantic_monitor.error",
                    {"error": str(error), "error_code": type(error).__name__},
                )

    def _queue_semantic(
        self,
        artifact_type: str,
        payload: Mapping[str, Any],
        path: Path,
        *,
        priority: int,
    ) -> Mapping[str, Any]:
        if self.transport is None:
            value = {
                "success": False,
                "state": "transport_unavailable",
                "error_code": "UWB_QUEUE_UNAVAILABLE",
                "error_message": "/uwb/queue_artifact is not wired",
            }
            self.events.publish(
                "semantic_monitor.transport_unavailable",
                {
                    "artifact_type": artifact_type,
                    "mission_id": payload.get("mission_id"),
                    "artifact_version": payload.get("artifact_version"),
                },
            )
            return value
        if artifact_type == "semantic_result":
            return dict(self.transport.send_semantic_result(payload, path, priority=priority))
        if artifact_type == "map_delta":
            return dict(self.transport.send_map_delta(payload, path, priority=priority))
        if artifact_type == "urgent_event":
            return dict(self.transport.send_urgent_event(payload, path, priority=priority))
        raise ValueError(f"unsupported semantic artifact type: {artifact_type}")

    @staticmethod
    def _durably_queued(value: Mapping[str, Any]) -> bool:
        return bool(value.get("success"))

    def _retry_full_resync(self, mission) -> Mapping[str, Any] | None:
        if not self._needs_full_resync:
            return None
        latest = self.manager.latest_result_version(
            mission.manifest.mission_id, mission.manifest.mission_version
        )
        if latest is None:
            self._needs_full_resync = False
            return None
        result = self.manager.load_semantic_result(
            mission.manifest.mission_id, mission.manifest.mission_version, latest
        )
        path = mission.directory / f"semantic_result_v{latest}.json"
        transfer = self._queue_semantic("semantic_result", result, path, priority=210)
        if self._durably_queued(transfer):
            self._needs_full_resync = False
            self.events.publish(
                "semantic_monitor.resync_queued",
                {"mission_id": mission.manifest.mission_id, "result_version": latest},
            )
            return {"state": "resync_queued", "result_version": latest, "transfer": transfer}
        return {"state": "waiting_for_uwb_queue", "result_version": latest, "transfer": transfer}

    def semantic_update_tick(self) -> Mapping[str, Any]:
        """Run one deterministic monitor iteration; tests can call this directly."""
        selected = self._selected_ref()
        if selected is None:
            return {"state": "inactive", "reason": "mission_not_selected"}
        if self.pipeline is None:
            raise ApiUnavailableError("analysis pipeline is not configured")
        with self._semantic_lock:
            mission = self._mission()
            recovery = self._retry_full_resync(mission)
            if recovery is not None:
                return recovery
            self._require_analysis_ready()
            version = (
                self.manager.latest_result_version(
                    mission.manifest.mission_id, mission.manifest.mission_version
                ) or 0
            ) + 1
            try:
                report = self.pipeline.run(
                    mission=mission.manifest,
                    candidates=self._candidates(),
                    result_version=version,
                    priorities={},
                    prior_map_path=mission.base_map_path,
                )
            except Exception as error:
                event = self._semantic_detector.mission_error(
                    mission.manifest.mission_id, max(1, version), error
                )
                if event is not None:
                    event_path = mission.directory / f"urgent_event_{event['event_id']}.json"
                    atomic_write_json(event_path, event)
                    self._queue_semantic(
                        "urgent_event", event, event_path,
                        priority=int(event.get("priority", 255)),
                    )
                raise

            result = report.result.to_dict()
            batch = self._semantic_detector.observe(result)
            if not batch.changed:
                self.events.publish(
                    "semantic_monitor.noop",
                    {
                        "mission_id": mission.manifest.mission_id,
                        "candidate_result_version": version,
                    },
                )
                return {"state": "no_change", "result_version": version - 1}

            result_path = self.manager.save_semantic_result(
                mission.manifest.mission_id, mission.manifest.mission_version, result
            )
            if report.stage4_artifacts is not None:
                self._write_stage4_artifacts(mission, report.stage4_artifacts)

            transfers: list[Mapping[str, Any]] = []
            if batch.delta is None:
                transfers.append(
                    self._queue_semantic("semantic_result", result, result_path, priority=200)
                )
                artifact_type = "semantic_result"
            else:
                delta = dict(batch.delta)
                delta_path = mission.directory / f"map_delta_v{version}.json"
                atomic_write_json(delta_path, delta)
                transfers.append(
                    self._queue_semantic("map_delta", delta, delta_path, priority=180)
                )
                artifact_type = "map_delta"

            primary_transfer = transfers[0]
            if not self._durably_queued(primary_transfer):
                self._needs_full_resync = True

            urgent_ids = []
            for event in batch.urgent_events:
                event_value = dict(event)
                event_path = mission.directory / f"urgent_event_{event_value['event_id']}.json"
                atomic_write_json(event_path, event_value)
                transfers.append(
                    self._queue_semantic(
                        "urgent_event", event_value, event_path,
                        priority=int(event_value.get("priority", 245)),
                    )
                )
                urgent_ids.append(event_value["event_id"])

            self.events.publish(
                "semantic_monitor.updated",
                {
                    "mission_id": mission.manifest.mission_id,
                    "mission_version": mission.manifest.mission_version,
                    "result_version": version,
                    "artifact_type": artifact_type,
                    "changed_keys": list(batch.changed_keys),
                    "urgent_event_ids": urgent_ids,
                },
            )
            return {
                "state": "updated",
                "artifact_type": artifact_type,
                "result_version": version,
                "changed_keys": list(batch.changed_keys),
                "urgent_event_ids": urgent_ids,
                "transfers": transfers,
            }

    def analyze(self):
        with self._semantic_lock:
            value = super().analyze()
            result = value.get("result")
            if isinstance(result, Mapping):
                self._semantic_detector.seed(result)
            return value


__all__ = ["ContinuousStage4JetsonApiService"]
