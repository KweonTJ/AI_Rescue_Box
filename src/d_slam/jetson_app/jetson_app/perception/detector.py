"""Configurable real detector adapter; model loading is caller supplied."""

from __future__ import annotations

from pathlib import Path
import threading
from typing import Callable, Sequence

from ..domain import BoundingBox
from ..providers.base import (
    DependencyUnavailableError,
    Detection2D,
    PersonDetectionProvider,
    ProviderMode,
    ProviderStatus,
    RgbFrame,
)


class ConfiguredPersonDetectionProvider(PersonDetectionProvider):
    """Wrap a detector callable without downloading or bundling a model."""

    def __init__(
        self,
        model_path: Path | None,
        detector: Callable[[RgbFrame, Path, float], Sequence[Detection2D]] | None,
        *,
        confidence_threshold: float = 0.5,
    ) -> None:
        self.model_path = Path(model_path) if model_path else None
        self.detector = detector
        self.confidence_threshold = confidence_threshold

    def status(self) -> ProviderStatus:
        if self.model_path is None:
            return ProviderStatus(
                "Person detector", ProviderMode.UNAVAILABLE, False, "model_path is not configured"
            )
        if not self.model_path.is_file():
            return ProviderStatus(
                "Person detector", ProviderMode.UNAVAILABLE, False, "configured model file is missing"
            )
        if self.detector is None:
            return ProviderStatus(
                "Person detector", ProviderMode.UNAVAILABLE, False, "detector runtime adapter is not installed"
            )
        return ProviderStatus(
            "Person detector", ProviderMode.REAL, True, "configured model loaded by runtime adapter"
        )

    def detect(self, frame: RgbFrame) -> Sequence[Detection2D]:
        status = self.status()
        if not status.connected or self.model_path is None or self.detector is None:
            raise DependencyUnavailableError(status.message)
        return tuple(
            detection
            for detection in self.detector(
                frame, self.model_path, self.confidence_threshold
            )
            if detection.class_name == "person"
            and detection.confidence >= self.confidence_threshold
        )


class OpenCvYoloPersonDetectionProvider(PersonDetectionProvider):
    """Real ONNX YOLO adapter using OpenCV DNN and caller-provided weights.

    Common YOLOv5 ``[N, 85]`` and YOLOv8 ``[N, 84]`` outputs are supported.
    No weights are downloaded or bundled.
    """

    def __init__(
        self,
        model_path: Path | None,
        *,
        confidence_threshold: float = 0.5,
        nms_threshold: float = 0.45,
        input_size: tuple[int, int] = (640, 640),
        person_class_id: int = 0,
    ) -> None:
        self.model_path = Path(model_path) if model_path else None
        self.confidence_threshold = confidence_threshold
        self.nms_threshold = nms_threshold
        self.input_size = input_size
        self.person_class_id = person_class_id
        self._network = None
        self._load_error = ""
        self._lock = threading.Lock()

    @staticmethod
    def _runtime():
        try:
            import cv2
            import numpy as np
        except ImportError as error:
            raise DependencyUnavailableError(
                "OpenCV and NumPy are required for ONNX person detection"
            ) from error
        return cv2, np

    def _load(self):
        if self._network is not None:
            return self._network
        if self.model_path is None or not self.model_path.is_file():
            raise DependencyUnavailableError("configured ONNX model file is missing")
        cv2, _ = self._runtime()
        try:
            self._network = cv2.dnn.readNetFromONNX(str(self.model_path))
        except Exception as error:
            self._load_error = str(error)
            raise DependencyUnavailableError(
                f"could not load configured ONNX model: {error}"
            ) from error
        return self._network

    def status(self) -> ProviderStatus:
        if self.model_path is None:
            return ProviderStatus(
                "OpenCV ONNX person detector",
                ProviderMode.UNAVAILABLE,
                False,
                "model_path is not configured",
            )
        if not self.model_path.is_file():
            return ProviderStatus(
                "OpenCV ONNX person detector",
                ProviderMode.UNAVAILABLE,
                False,
                "configured ONNX model file is missing",
            )
        try:
            self._runtime()
        except DependencyUnavailableError as error:
            return ProviderStatus(
                "OpenCV ONNX person detector", ProviderMode.UNAVAILABLE, False, str(error)
            )
        if self._load_error:
            return ProviderStatus(
                "OpenCV ONNX person detector",
                ProviderMode.UNAVAILABLE,
                False,
                self._load_error,
            )
        return ProviderStatus(
            "OpenCV ONNX person detector",
            ProviderMode.REAL,
            True,
            (
                f"configured model loaded: {self.model_path}"
                if self._network is not None
                else f"configured model ready for worker load: {self.model_path}"
            ),
        )

    @staticmethod
    def _image_array(frame: RgbFrame):
        cv2, np = OpenCvYoloPersonDetectionProvider._runtime()
        if isinstance(frame.data, np.ndarray):
            image = frame.data
            if frame.encoding.lower() == "rgb8":
                image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
            return image
        try:
            from cv_bridge import CvBridge
        except ImportError as error:
            raise DependencyUnavailableError(
                "cv_bridge is required to decode ROS Image messages"
            ) from error
        return CvBridge().imgmsg_to_cv2(frame.data, desired_encoding="bgr8")

    def detect(self, frame: RgbFrame) -> Sequence[Detection2D]:
        cv2, np = self._runtime()
        image = self._image_array(frame)
        network = self._load()
        with self._lock:
            blob = cv2.dnn.blobFromImage(
                image,
                scalefactor=1.0 / 255.0,
                size=self.input_size,
                swapRB=True,
                crop=False,
            )
            network.setInput(blob)
            output = network.forward()
        rows = np.squeeze(np.asarray(output))
        if rows.ndim != 2:
            raise RuntimeError(f"unsupported YOLO output dimensions: {rows.shape}")
        if rows.shape[0] in {84, 85} and rows.shape[1] > rows.shape[0]:
            rows = rows.T
        input_width, input_height = self.input_size
        scale_x = frame.width / input_width
        scale_y = frame.height / input_height
        boxes, scores = [], []
        for row in rows:
            if len(row) < 6:
                continue
            if len(row) == 84:
                class_scores = row[4:]
                class_id = int(np.argmax(class_scores))
                confidence = float(class_scores[class_id])
            else:
                class_scores = row[5:]
                class_id = int(np.argmax(class_scores))
                confidence = float(row[4]) * float(class_scores[class_id])
            if class_id != self.person_class_id or confidence < self.confidence_threshold:
                continue
            cx, cy, width, height = map(float, row[:4])
            boxes.append(
                [
                    int((cx - width / 2) * scale_x),
                    int((cy - height / 2) * scale_y),
                    max(1, int(width * scale_x)),
                    max(1, int(height * scale_y)),
                ]
            )
            scores.append(confidence)
        indices = cv2.dnn.NMSBoxes(
            boxes, scores, self.confidence_threshold, self.nms_threshold
        )
        detections = []
        for raw_index in indices:
            index = int(np.asarray(raw_index).reshape(-1)[0])
            x, y, width, height = boxes[index]
            detections.append(
                Detection2D(
                    bbox=BoundingBox(x, y, width, height),
                    confidence=scores[index],
                    class_name="person",
                    timestamp=frame.timestamp,
                )
            )
        return tuple(detections)
