#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

import mediapipe as mp
import numpy as np
import rclpy

from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image
from std_msgs.msg import String


MODEL = os.environ.get(
    "AI_RESCUE_MEDIAPIPE_MODEL",
    "/home/a/mediapipe_test/models/efficientdet_lite0.tflite",
)

RGB_TOPIC = os.environ.get(
    "AI_RESCUE_RGB_TOPIC",
    "/camera/color/image_raw",
)

OUTPUT_TOPIC = os.environ.get(
    "AI_RESCUE_EXTERNAL_PERSON_TOPIC",
    "/ai_rescue/mediapipe_person_detections",
)

CONFIDENCE = float(
    os.environ.get(
        "AI_RESCUE_MEDIAPIPE_CONFIDENCE",
        "0.70",
    )
)

INTERVAL = float(
    os.environ.get(
        "AI_RESCUE_MEDIAPIPE_INTERVAL_S",
        "0.70",
    )
)


def stamp_to_iso(stamp) -> str:
    seconds = int(stamp.sec)
    nanoseconds = int(stamp.nanosec)

    return datetime.fromtimestamp(
        seconds + nanoseconds / 1_000_000_000,
        tz=timezone.utc,
    ).isoformat().replace("+00:00", "Z")


def rgb_array(msg: Image) -> np.ndarray:
    encoding = msg.encoding.lower()

    if encoding in ("rgb8", "bgr8"):
        channels = 3
    elif encoding in ("rgba8", "bgra8"):
        channels = 4
    else:
        raise ValueError(
            f"unsupported RGB encoding: {msg.encoding}"
        )

    raw = np.frombuffer(
        msg.data,
        dtype=np.uint8,
    )

    rows = raw.reshape(
        msg.height,
        msg.step,
    )

    frame = rows[
        :,
        : msg.width * channels,
    ].reshape(
        msg.height,
        msg.width,
        channels,
    )

    if encoding == "rgb8":
        rgb = frame

    elif encoding == "bgr8":
        rgb = frame[:, :, ::-1]

    elif encoding == "rgba8":
        rgb = frame[:, :, :3]

    else:
        rgb = frame[:, :, [2, 1, 0]]

    return np.ascontiguousarray(rgb)


class MediaPipePersonBridge(Node):
    def __init__(self) -> None:
        super().__init__("ai_rescue_mediapipe_person_bridge")

        options = mp.tasks.vision.ObjectDetectorOptions(
            base_options=mp.tasks.BaseOptions(
                model_asset_path=MODEL,
            ),
            running_mode=mp.tasks.vision.RunningMode.IMAGE,
            max_results=5,
            score_threshold=CONFIDENCE,
            category_allowlist=["person"],
        )

        self.detector = (
            mp.tasks.vision.ObjectDetector.create_from_options(
                options
            )
        )

        self.publisher = self.create_publisher(
            String,
            OUTPUT_TOPIC,
            10,
        )

        self.subscription = self.create_subscription(
            Image,
            RGB_TOPIC,
            self.on_rgb,
            qos_profile_sensor_data,
        )

        self.last_inference = 0.0
        self.frame_number = 0

        print()
        print("========================================")
        print("AI Rescue Box MediaPipe Bridge")
        print("========================================")
        print("RGB topic   :", RGB_TOPIC)
        print("Output      :", OUTPUT_TOPIC)
        print("Model       :", MODEL)
        print("Confidence  :", CONFIDENCE)
        print("Interval    :", INTERVAL, "s")
        print("========================================")
        print()

    def on_rgb(self, msg: Image) -> None:
        now = time.monotonic()

        if now - self.last_inference < INTERVAL:
            return

        self.last_inference = now
        self.frame_number += 1

        try:
            rgb = rgb_array(msg)

            image = mp.Image(
                image_format=mp.ImageFormat.SRGB,
                data=rgb,
            )

            started = time.perf_counter()

            result = self.detector.detect(image)

            elapsed_ms = (
                time.perf_counter() - started
            ) * 1000.0

            timestamp = stamp_to_iso(
                msg.header.stamp
            )

            detections = []

            for index, detection in enumerate(
                result.detections
            ):
                if not detection.categories:
                    continue

                category = detection.categories[0]

                if (
                    category.category_name != "person"
                    or category.score < CONFIDENCE
                ):
                    continue

                bbox = detection.bounding_box

                detections.append(
                    {
                        "detection_id": (
                            f"mediapipe-{timestamp}-{index}"
                        ),
                        "confidence": float(
                            category.score
                        ),
                        "bbox": {
                            "x": float(bbox.origin_x),
                            "y": float(bbox.origin_y),
                            "width": float(bbox.width),
                            "height": float(bbox.height),
                        },
                    }
                )

            message = String()

            message.data = json.dumps(
                {
                    "timestamp": timestamp,
                    "image_width": int(msg.width),
                    "image_height": int(msg.height),
                    "detections": detections,
                },
                separators=(",", ":"),
            )

            # 사람이 없어도 heartbeat 목적으로 publish
            self.publisher.publish(message)

            if detections:
                print(
                    f"[PERSON] frame={self.frame_number} "
                    f"count={len(detections)} "
                    f"inference={elapsed_ms:.1f}ms"
                )

                for item in detections:
                    b = item["bbox"]

                    print(
                        f"  confidence={item['confidence']:.3f} "
                        f"bbox=({b['x']:.0f},"
                        f"{b['y']:.0f},"
                        f"{b['width']:.0f},"
                        f"{b['height']:.0f})"
                    )

        except Exception as error:
            self.get_logger().error(
                f"MediaPipe inference failed: {error}"
            )

    def destroy_node(self):
        self.detector.close()
        return super().destroy_node()


def main():
    rclpy.init()

    node = MediaPipePersonBridge()

    try:
        rclpy.spin(node)

    except KeyboardInterrupt:
        pass

    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
