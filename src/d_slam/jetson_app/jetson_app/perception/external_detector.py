from __future__ import annotations

import json
import threading
import time

from ..domain import BoundingBox
from ..providers.base import (
    Detection2D,
    PersonDetectionProvider,
    ProviderMode,
    ProviderStatus,
    RgbFrame,
)


class RosTopicPersonDetectionProvider(PersonDetectionProvider):
    """Consume person boxes produced by an external MediaPipe ROS process."""

    source_name = "mediapipe_object_detector"

    def __init__(
        self,
        topic: str,
        *,
        confidence_threshold: float = 0.7,
        stale_after_s: float = 3.0,
    ) -> None:
        self.topic = str(topic)
        self.confidence_threshold = float(confidence_threshold)
        self.stale_after_s = float(stale_after_s)

        self._lock = threading.RLock()
        self._pending: tuple[Detection2D, ...] = ()
        self._generation = 0
        self._consumed_generation = 0
        self._last_heartbeat = 0.0
        self._last_error = ""

    def update_json(self, payload: str) -> None:
        try:
            value = json.loads(payload)

            if not isinstance(value, dict):
                raise ValueError("MediaPipe payload must be an object")

            timestamp = value.get("timestamp")
            if not isinstance(timestamp, str) or not timestamp:
                raise ValueError("MediaPipe payload requires timestamp")

            raw_detections = value.get("detections", [])
            if not isinstance(raw_detections, list):
                raise ValueError("detections must be an array")

            detections = []

            for index, item in enumerate(raw_detections):
                if not isinstance(item, dict):
                    continue

                confidence = float(item.get("confidence", 0.0))

                if confidence < self.confidence_threshold:
                    continue

                bbox = BoundingBox.from_value(item.get("bbox"))

                detections.append(
                    Detection2D(
                        bbox=bbox,
                        confidence=confidence,
                        class_name="person",
                        tracking_id=(
                            str(item["tracking_id"])
                            if item.get("tracking_id")
                            else None
                        ),
                        detection_id=(
                            str(item["detection_id"])
                            if item.get("detection_id")
                            else f"mediapipe-{timestamp}-{index}"
                        ),
                        timestamp=timestamp,
                    )
                )

            with self._lock:
                self._pending = tuple(detections)
                self._generation += 1
                self._last_heartbeat = time.monotonic()
                self._last_error = ""

        except Exception as error:
            with self._lock:
                self._last_error = str(error)
            raise

    def status(self) -> ProviderStatus:
        with self._lock:
            heartbeat = self._last_heartbeat
            error = self._last_error

        connected = (
            heartbeat > 0.0
            and time.monotonic() - heartbeat <= self.stale_after_s
        )

        if error:
            message = f"external MediaPipe payload error: {error}"
        elif connected:
            message = f"receiving MediaPipe detections on {self.topic}"
        else:
            message = f"waiting for MediaPipe detections on {self.topic}"

        return ProviderStatus(
            "MediaPipe person detector",
            ProviderMode.REAL if connected else ProviderMode.UNAVAILABLE,
            connected,
            message,
        )

    def detect(self, frame: RgbFrame):
        del frame

        with self._lock:
            if (
                self._last_heartbeat <= 0.0
                or time.monotonic() - self._last_heartbeat > self.stale_after_s
            ):
                return ()

            # 같은 MediaPipe detection을 RGB 30fps마다 반복 처리하지 않음
            if self._generation == self._consumed_generation:
                return ()

            self._consumed_generation = self._generation
            return self._pending
