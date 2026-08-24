"""Optional multi-class RGB hazard detection fused with measured depth."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..domain import ObservationState, Point2D, RiskZone
from ..providers.base import (
    DependencyUnavailableError,
    Detection2D,
    DepthProvider,
    MapTransformer,
    PersonDetectionProvider,
    ProviderMode,
    ProviderStatus,
    RgbFrame,
)

HAZARD_CLASSES = (
    "person",
    "debris",
    "blocked_passage",
    "hole_or_drop",
    "stair_or_step",
    "smoke",
    "fire",
    "structural_damage_candidate",
)

DEFAULT_HAZARD_CLASS_MAP = {
    0: "person",
    1: "debris",
    2: "blocked_passage",
    3: "hole_or_drop",
    4: "stair_or_step",
    5: "smoke",
    6: "fire",
    7: "structural_damage_candidate",
}

_SEVERITY = {
    "debris": 0.65,
    "blocked_passage": 0.80,
    "hole_or_drop": 0.90,
    "stair_or_step": 0.55,
    "smoke": 0.70,
    "fire": 0.95,
    "structural_damage_candidate": 0.65,
}


def _class_map_from_environment() -> dict[int, str]:
    raw = os.environ.get("AI_RESCUE_HAZARD_CLASS_MAP", "").strip()
    if not raw:
        return dict(DEFAULT_HAZARD_CLASS_MAP)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("AI_RESCUE_HAZARD_CLASS_MAP must be JSON") from error
    if not isinstance(value, Mapping):
        raise ValueError("AI_RESCUE_HAZARD_CLASS_MAP must be a JSON object")
    result: dict[int, str] = {}
    for raw_key, raw_name in value.items():
        try:
            key = int(raw_key)
        except (TypeError, ValueError) as error:
            raise ValueError("hazard class-map keys must be integer ids") from error
        name = str(raw_name).strip()
        if name not in HAZARD_CLASSES:
            raise ValueError(f"unsupported hazard class name: {name}")
        result[key] = name
    return result


class OpenCvYoloHazardDetectionProvider(PersonDetectionProvider):
    """Load an optional custom YOLO/ONNX model without affecting person fallback."""

    def __init__(
        self,
        model_path: Path | None,
        *,
        confidence_threshold: float = 0.5,
        nms_threshold: float = 0.45,
        class_map: Mapping[int, str] | None = None,
    ) -> None:
        self.model_path = None if model_path is None else Path(model_path).expanduser()
        self.confidence_threshold = float(confidence_threshold)
        self.nms_threshold = float(nms_threshold)
        self.class_map = dict(class_map or DEFAULT_HAZARD_CLASS_MAP)
        self._net: Any | None = None
        self._cv2: Any | None = None
        self._error = ""
        if self.model_path is None:
            self._error = "AI_RESCUE_HAZARD_MODEL is not configured"
            return
        if not self.model_path.is_file():
            self._error = f"hazard model does not exist: {self.model_path}"
            return
        try:
            import cv2  # type: ignore

            self._cv2 = cv2
            self._net = cv2.dnn.readNet(str(self.model_path))
        except Exception as error:
            self._error = f"hazard model load failed: {error}"

    @classmethod
    def from_environment(
        cls, *, confidence_threshold: float = 0.5
    ) -> "OpenCvYoloHazardDetectionProvider":
        raw_path = os.environ.get("AI_RESCUE_HAZARD_MODEL", "").strip()
        raw_conf = os.environ.get("AI_RESCUE_HAZARD_CONFIDENCE", "").strip()
        threshold = float(raw_conf) if raw_conf else float(confidence_threshold)
        return cls(
            Path(raw_path) if raw_path else None,
            confidence_threshold=threshold,
            class_map=_class_map_from_environment(),
        )

    def status(self) -> ProviderStatus:
        connected = self._net is not None and not self._error
        return ProviderStatus(
            name="multi-class RGB hazard detector",
            mode=ProviderMode.REAL if connected else ProviderMode.UNAVAILABLE,
            connected=connected,
            message=(
                f"model ready: {self.model_path}"
                if connected
                else self._error or "hazard detector unavailable"
            ),
        )

    @staticmethod
    def _frame_array(frame: RgbFrame, cv2: Any) -> Any:
        import numpy as np  # type: ignore

        data = frame.data
        if hasattr(data, "shape"):
            image = data
        else:
            channels = 3
            raw = np.frombuffer(bytes(data), dtype=np.uint8)
            expected = frame.width * frame.height * channels
            if raw.size < expected:
                raise ValueError("RGB frame buffer is too small")
            image = raw[:expected].reshape((frame.height, frame.width, channels))
        encoding = frame.encoding.lower()
        if encoding == "rgb8":
            image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        elif encoding not in {"bgr8", "8uc3"}:
            raise ValueError(f"unsupported RGB encoding: {frame.encoding}")
        return image

    def detect(self, frame: RgbFrame) -> Sequence[Detection2D]:
        if self._net is None or self._cv2 is None:
            raise DependencyUnavailableError(self._error or "hazard model unavailable")
        cv2 = self._cv2
        image = self._frame_array(frame, cv2)
        blob = cv2.dnn.blobFromImage(
            image, 1.0 / 255.0, (640, 640), swapRB=False, crop=False
        )
        self._net.setInput(blob)
        raw = self._net.forward()
        rows = raw
        if getattr(raw, "ndim", 0) == 3:
            rows = raw[0]
        if getattr(rows, "shape", (0, 0))[0] < getattr(rows, "shape", (0, 0))[-1]:
            rows = rows.T

        boxes: list[list[int]] = []
        scores: list[float] = []
        class_ids: list[int] = []
        for row in rows:
            values = list(float(item) for item in row)
            if len(values) < 6:
                continue
            class_scores = values[4:]
            class_id = max(range(len(class_scores)), key=class_scores.__getitem__)
            score = float(class_scores[class_id])
            name = self.class_map.get(class_id)
            if score < self.confidence_threshold or name not in HAZARD_CLASSES:
                continue
            cx, cy, width, height = values[:4]
            if max(abs(cx), abs(cy), abs(width), abs(height)) <= 2.0:
                cx *= frame.width
                cy *= frame.height
                width *= frame.width
                height *= frame.height
            x = max(0, int(round(cx - width / 2)))
            y = max(0, int(round(cy - height / 2)))
            w = max(1, min(frame.width - x, int(round(width))))
            h = max(1, min(frame.height - y, int(round(height))))
            boxes.append([x, y, w, h])
            scores.append(score)
            class_ids.append(class_id)
        if not boxes:
            return ()
        indices = cv2.dnn.NMSBoxes(
            boxes, scores, self.confidence_threshold, self.nms_threshold
        )
        flattened = []
        for item in indices:
            flattened.append(int(item[0]) if isinstance(item, (list, tuple)) else int(item))
        from ..domain import BoundingBox

        detections = []
        for index in flattened:
            x, y, width, height = boxes[index]
            name = self.class_map[class_ids[index]]
            seed = (
                f"{frame.timestamp}:{name}:{x}:{y}:{width}:{height}:"
                f"{scores[index]:.6f}"
            )
            detections.append(
                Detection2D(
                    bbox=BoundingBox(float(x), float(y), float(width), float(height)),
                    confidence=scores[index],
                    class_name=name,
                    detection_id=(
                        f"hazard-{name}-"
                        f"{hashlib.sha256(seed.encode()).hexdigest()[:12]}"
                    ),
                    timestamp=frame.timestamp,
                )
            )
        return tuple(detections)


class HazardFusionEngine:
    """Turn non-person RGB detections into map-frame risk candidates using depth."""

    def __init__(
        self,
        detector: PersonDetectionProvider,
        depth: DepthProvider,
        transformer: MapTransformer,
        *,
        radius_m: float = 0.30,
    ) -> None:
        self.detector = detector
        self.depth = depth
        self.transformer = transformer
        self.radius_m = max(0.10, float(radius_m))

    def process(self, frame: RgbFrame) -> tuple[RiskZone, ...]:
        risks: list[RiskZone] = []
        depth_size = self.depth.measurement_image_size()
        for detection in self.detector.detect(frame):
            if detection.class_name == "person":
                continue
            if detection.class_name not in HAZARD_CLASSES:
                continue
            camera_point = (
                self.depth.locate(detection)
                if depth_size is None or depth_size == (frame.width, frame.height)
                else None
            )
            if camera_point is None:
                continue
            depth_frame = self.depth.measurement_frame_id()
            if not depth_frame:
                continue
            map_point = self.transformer.camera_to_map(
                camera_point,
                timestamp=detection.timestamp,
                frame_id=depth_frame,
            )
            if map_point is None:
                continue
            radius = self.radius_m
            polygon = (
                Point2D(map_point.x - radius, map_point.y - radius),
                Point2D(map_point.x + radius, map_point.y - radius),
                Point2D(map_point.x + radius, map_point.y + radius),
                Point2D(map_point.x - radius, map_point.y + radius),
            )
            risk_type = detection.class_name
            severity = _SEVERITY.get(risk_type, 0.6)
            confidence = min(0.90, max(0.05, detection.confidence) * 0.85)
            wording = (
                "visual structural-damage sign candidate"
                if risk_type == "structural_damage_candidate"
                else f"visual {risk_type} candidate"
            )
            risks.append(
                RiskZone(
                    risk_id=detection.detection_id or f"rgb-{risk_type}-{len(risks) + 1}",
                    risk_type=risk_type,
                    polygon=polygon,
                    severity=severity,
                    confidence=confidence,
                    rationale=(
                        f"{wording}; location is supported by measured depth. "
                        "This is a risk candidate, not a confirmed hazard."
                    ),
                    source="rgb_ai+measured_depth",
                    observed_at=detection.timestamp,
                    state=ObservationState.OBSERVED,
                )
            )
        return tuple(risks)


def _center(risk: RiskZone) -> Point2D:
    return Point2D(
        sum(point.x for point in risk.polygon) / len(risk.polygon),
        sum(point.y for point in risk.polygon) / len(risk.polygon),
    )


_SUPPORT = {
    "debris": {"debris_dense_candidate", "obstacle_candidate"},
    "blocked_passage": {
        "obstacle_candidate",
        "insufficient_passage_width_candidate",
        "path_disconnection_candidate",
    },
    "hole_or_drop": {"fall_hazard_candidate"},
    "stair_or_step": {"sudden_step_candidate"},
}


def fuse_ai_with_sensor_risks(
    risks: Sequence[RiskZone], *, support_distance_m: float = 0.9
) -> tuple[RiskZone, ...]:
    """Boost only AI candidates corroborated by an independent rule/sensor risk."""
    from dataclasses import replace

    output: list[RiskZone] = []
    for risk in risks:
        if not risk.source.startswith("rgb_ai+"):
            output.append(risk)
            continue
        related = _SUPPORT.get(risk.risk_type, set())
        if not related:
            output.append(risk)
            continue
        center = _center(risk)
        supports = []
        for other in risks:
            if other is risk or other.risk_type not in related:
                continue
            other_center = _center(other)
            if math.hypot(center.x - other_center.x, center.y - other_center.y) <= support_distance_m:
                supports.append(other)
        if not supports:
            output.append(risk)
            continue
        strongest = max(supports, key=lambda item: (item.confidence, item.severity))
        output.append(
            replace(
                risk,
                confidence=min(0.99, risk.confidence + 0.15 * strongest.confidence),
                severity=max(risk.severity, min(1.0, strongest.severity)),
                source=f"{risk.source}+{strongest.source}",
                rationale=(
                    f"{risk.rationale} Corroborated by "
                    f"{strongest.risk_type} ({strongest.risk_id})."
                ),
            )
        )
    return tuple(output)


__all__ = [
    "DEFAULT_HAZARD_CLASS_MAP",
    "HAZARD_CLASSES",
    "HazardFusionEngine",
    "OpenCvYoloHazardDetectionProvider",
    "fuse_ai_with_sensor_risks",
]
