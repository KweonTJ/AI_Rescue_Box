"""Business-plan aligned extensions built on existing Jetson services.

The extension reuses the current Mission repository, durable UWB action,
person/depth fusion, and sensor-risk pipeline. Missing hazard weights never
become an analysis-readiness dependency.
"""
from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .perception.hazards import HazardFusionEngine, OpenCvYoloHazardDetectionProvider
from .providers.base import RgbFrame

_INSTALLED = False
_LATEST_TRANSPORT: Any | None = None
_TRANSPORT_LOCK = threading.RLock()


def _record_host_sync(applied: Any, value: dict[str, Any]) -> None:
    path = Path(applied.directory) / "host_sync.json"
    temporary = path.with_name(f".{path.name}.part")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def install_business_plan_extensions() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from .api.uwb_transport import RosUwbArtifactTransport
    from .domain import SemanticResult
    from .mission.tablet_ingest import TabletMissionIngestor
    from . import semantic_updates
    from .ros_client.adapters import RosMapTransformer
    from .ros_client.sensor_node import ros_stamp_to_iso
    from .runtime import Stage3Runtime, Stage3SensorRosNode, _provider_status

    original_semantic_to_dict = SemanticResult.to_dict

    def semantic_to_dict(self: Any) -> dict[str, Any]:
        value = original_semantic_to_dict(self)
        value["return_routes"] = [
            dict(item) for item in getattr(self, "_return_routes", ())
        ]
        enriched = []
        for raw in value.get("risk_zones", []):
            item = dict(raw)
            source = str(item.get("source", "")).strip()
            rationale = str(item.get("rationale", "")).strip()
            item.setdefault(
                "evidence",
                {
                    "sources": [part for part in source.split("+") if part],
                    "rationale": rationale,
                },
            )
            enriched.append(item)
        value["risk_zones"] = enriched
        return value

    SemanticResult.to_dict = semantic_to_dict  # type: ignore[assignment]
    if "return_routes" not in semantic_updates.SEMANTIC_KEYS:
        semantic_updates.SEMANTIC_KEYS = (*semantic_updates.SEMANTIC_KEYS, "return_routes")

    original_transport_init = RosUwbArtifactTransport.__init__

    def transport_init(self: Any, *args: Any, **kwargs: Any) -> None:
        global _LATEST_TRANSPORT
        original_transport_init(self, *args, **kwargs)
        with _TRANSPORT_LOCK:
            _LATEST_TRANSPORT = self

    RosUwbArtifactTransport.__init__ = transport_init  # type: ignore[assignment]

    def send_tablet_mission(
        self: Any,
        applied: Any,
        *,
        base_priority: int = 190,
        manifest_priority: int = 185,
    ) -> dict[str, Any]:
        manifest = applied.manifest
        base = self._send(
            Path(applied.base_map_path),
            artifact_type="base_map",
            mission_id=manifest.mission_id,
            artifact_version=manifest.mission_version,
            priority=base_priority,
        )
        metadata = self._send(
            Path(applied.manifest_path),
            artifact_type="mission_manifest",
            mission_id=manifest.mission_id,
            artifact_version=manifest.mission_version,
            priority=manifest_priority,
        )
        return {
            "success": True,
            "base_map": dict(base),
            "mission_manifest": dict(metadata),
        }

    RosUwbArtifactTransport.send_tablet_mission = send_tablet_mission  # type: ignore[attr-defined]

    original_store = TabletMissionIngestor.store

    def store_and_mirror(self: Any, *args: Any, **kwargs: Any) -> Any:
        applied = original_store(self, *args, **kwargs)
        with _TRANSPORT_LOCK:
            transport = _LATEST_TRANSPORT
        if transport is None:
            _record_host_sync(
                applied,
                {
                    "state": "waiting_for_uwb",
                    "success": False,
                    "mission_id": applied.manifest.mission_id,
                    "mission_version": applied.manifest.mission_version,
                },
            )
            return applied
        try:
            receipt = transport.send_tablet_mission(applied)
            _record_host_sync(
                applied,
                {
                    "state": "queued",
                    "mission_id": applied.manifest.mission_id,
                    "mission_version": applied.manifest.mission_version,
                    **receipt,
                },
            )
        except Exception as error:
            # Local STORED remains usable even while Host/UWB is unavailable.
            _record_host_sync(
                applied,
                {
                    "state": "sync_failed",
                    "success": False,
                    "mission_id": applied.manifest.mission_id,
                    "mission_version": applied.manifest.mission_version,
                    "error": str(error),
                },
            )
        return applied

    TabletMissionIngestor.store = store_and_mirror  # type: ignore[assignment]

    original_runtime_init = Stage3Runtime.__init__

    def runtime_init(self: Any, config: Any) -> None:
        original_runtime_init(self, config)
        self.hazard_detector = None
        if getattr(config, "mode", "") == "mock":
            return
        detector = OpenCvYoloHazardDetectionProvider.from_environment(
            confidence_threshold=float(getattr(config, "detection_confidence", 0.5))
        )
        self.hazard_detector = detector
        if (
            self.sensor_node is None
            or self.depth is None
            or not detector.status().connected
        ):
            return
        transformer = RosMapTransformer(
            self.sensor_node.camera_to_map,
            target_frame=config.slam_map_frame,
        )
        self.sensor_node._hazard_fusion = HazardFusionEngine(
            detector, self.depth, transformer
        )
        self.sensor_node._hazard_inference_pool = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="jetson-hazard-inference"
        )
        self.sensor_node._hazard_inference_pending = threading.Event()

    Stage3Runtime.__init__ = runtime_init  # type: ignore[assignment]

    original_on_rgb = Stage3SensorRosNode._on_rgb

    def on_rgb(self: Any, message: Any) -> None:
        # Existing Person+Depth inference stays authoritative.
        original_on_rgb(self, message)
        fusion = getattr(self, "_hazard_fusion", None)
        pending = getattr(self, "_hazard_inference_pending", None)
        pool = getattr(self, "_hazard_inference_pool", None)
        if fusion is None or pending is None or pool is None or pending.is_set():
            return
        pending.set()
        with self._state_lock:
            mission_epoch = self._mission_epoch
        frame = RgbFrame(
            int(message.width),
            int(message.height),
            message,
            str(message.encoding),
            str(message.header.frame_id),
            ros_stamp_to_iso(message.header.stamp),
        )
        future = pool.submit(fusion.process, frame)

        def complete(completed: Any) -> None:
            try:
                risks = tuple(completed.result())
                with self._state_lock:
                    if mission_epoch != self._mission_epoch:
                        return
                    self._sensor_risks["rgb_ai"] = risks
                self._update_slam()
            except Exception as error:
                self.get_logger().error(
                    f"multi-class hazard inference failed: {error}"
                )
            finally:
                pending.clear()

        future.add_done_callback(complete)

    Stage3SensorRosNode._on_rgb = on_rgb  # type: ignore[assignment]

    original_reset = Stage3SensorRosNode.reset_mission_state

    def reset_mission_state(self: Any) -> None:
        original_reset(self)
        with self._state_lock:
            self._sensor_risks.pop("rgb_ai", None)

    Stage3SensorRosNode.reset_mission_state = reset_mission_state  # type: ignore[assignment]

    original_status = Stage3Runtime._real_component_status

    def real_component_status(self: Any) -> dict[str, Any]:
        values = dict(original_status(self))
        detector = getattr(self, "hazard_detector", None)
        if detector is not None:
            values["hazard_model"] = _provider_status(
                detector.status(), code="HAZARD_MODEL_OPTIONAL"
            )
        return values

    Stage3Runtime._real_component_status = real_component_status  # type: ignore[assignment]
