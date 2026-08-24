from __future__ import annotations

from jetson_app.domain import BoundingBox, CameraPoint, ObservationState, Point2D, RiskZone
from jetson_app.perception.hazards import HazardFusionEngine, fuse_ai_with_sensor_risks
from jetson_app.providers.base import (
    Detection2D,
    DepthProvider,
    MapTransformer,
    PersonDetectionProvider,
    ProviderMode,
    ProviderStatus,
    RgbFrame,
)

STAMP = "2026-08-24T00:00:00Z"


class _Detector(PersonDetectionProvider):
    def status(self):
        return ProviderStatus("synthetic multi-class", ProviderMode.REAL, True, "ready")

    def detect(self, frame):
        names = ["person", "debris", "blocked_passage", "hole_or_drop", "stair_or_step"]
        return tuple(
            Detection2D(
                bbox=BoundingBox(index * 5, 0, 4, 4),
                confidence=0.9,
                class_name=name,
                detection_id=f"d-{name}",
                timestamp=STAMP,
            )
            for index, name in enumerate(names)
        )


class _Depth(DepthProvider):
    def status(self):
        return ProviderStatus("depth", ProviderMode.REAL, True, "ready")

    def locate(self, detection):
        return CameraPoint(detection.bbox.x / 10.0, 0.0, 2.0)

    def measurement_frame_id(self):
        return "camera_depth_optical_frame"


class _Transform(MapTransformer):
    def camera_to_map(self, point, *, timestamp, frame_id):
        return Point2D(point.x, point.z)


def test_synthetic_multiclass_hazards_become_depth_supported_risk_candidates():
    engine = HazardFusionEngine(_Detector(), _Depth(), _Transform())
    risks = engine.process(RgbFrame(100, 100, b"", timestamp=STAMP))

    # Person stays on the existing Person+Depth path and is not duplicated as a risk.
    assert {risk.risk_type for risk in risks} == {
        "debris",
        "blocked_passage",
        "hole_or_drop",
        "stair_or_step",
    }
    for risk in risks:
        assert risk.source == "rgb_ai+measured_depth"
        assert 0 < risk.confidence <= 1
        assert 0 < risk.severity <= 1
        assert "candidate" in risk.rationale.lower()
        assert risk.state is ObservationState.OBSERVED


def test_ai_candidate_confidence_is_boosted_only_with_independent_sensor_support():
    ai = HazardFusionEngine(_Detector(), _Depth(), _Transform()).process(
        RgbFrame(100, 100, b"", timestamp=STAMP)
    )
    debris = next(item for item in ai if item.risk_type == "debris")
    center = debris.polygon[0]
    support = RiskZone(
        risk_id="depth-debris",
        risk_type="debris_dense_candidate",
        polygon=(
            center,
            Point2D(center.x + 0.1, center.y),
            Point2D(center.x + 0.1, center.y + 0.1),
        ),
        severity=0.8,
        confidence=0.9,
        rationale="depth geometry",
        source="registered_depth",
        observed_at=STAMP,
        state=ObservationState.OBSERVED,
    )
    fused = fuse_ai_with_sensor_risks((*ai, support))
    fused_debris = next(item for item in fused if item.risk_id == debris.risk_id)
    assert fused_debris.confidence > debris.confidence
    assert "registered_depth" in fused_debris.source
