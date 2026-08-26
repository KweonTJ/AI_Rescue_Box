#!/usr/bin/env python3

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import mediapipe as mp
import numpy as np
import rclpy
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image


LOCK = threading.Lock()

RGB_JPEG = b""
DEPTH_JPEG = b""

STATUS = {
    "rgb_ready": False,
    "depth_ready": False,
    "person_count": 0,
    "confidence": 0.0,
    "updated_at": 0.0,
    "obstacle_count": 0,
    "nearest_obstacle_m": None,
}


def encode_jpeg(image, quality=78):
    ok, encoded = cv2.imencode(
        ".jpg",
        image,
        [cv2.IMWRITE_JPEG_QUALITY, quality],
    )
    return encoded.tobytes() if ok else b""


def placeholder(title, subtitle):
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    img[:] = (22, 24, 26)

    cv2.putText(
        img,
        title,
        (35, 215),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,
        (240, 240, 240),
        2,
        cv2.LINE_AA,
    )

    cv2.putText(
        img,
        subtitle,
        (35, 255),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.58,
        (150, 160, 170),
        1,
        cv2.LINE_AA,
    )

    return encode_jpeg(img)


def rgb_msg_to_bgr(msg):
    enc = msg.encoding.lower()

    if enc in ("rgb8", "bgr8"):
        row = np.frombuffer(
            msg.data,
            dtype=np.uint8,
        ).reshape(msg.height, msg.step)

        image = row[:, : msg.width * 3].reshape(
            msg.height,
            msg.width,
            3,
        ).copy()

        if enc == "rgb8":
            image = cv2.cvtColor(
                image,
                cv2.COLOR_RGB2BGR,
            )

        return image

    if enc in ("rgba8", "bgra8"):
        row = np.frombuffer(
            msg.data,
            dtype=np.uint8,
        ).reshape(msg.height, msg.step)

        image = row[:, : msg.width * 4].reshape(
            msg.height,
            msg.width,
            4,
        ).copy()

        if enc == "rgba8":
            return cv2.cvtColor(
                image,
                cv2.COLOR_RGBA2BGR,
            )

        return cv2.cvtColor(
            image,
            cv2.COLOR_BGRA2BGR,
        )

    raise RuntimeError(
        f"Unsupported RGB encoding: {msg.encoding}"
    )


def depth_msg_to_array(msg):
    enc = msg.encoding.lower()

    if enc in ("16uc1", "mono16"):
        stride = msg.step // 2

        arr = np.frombuffer(
            msg.data,
            dtype=np.uint16,
        ).reshape(msg.height, stride)

        return arr[:, : msg.width].copy()

    if enc == "32fc1":
        stride = msg.step // 4

        arr = np.frombuffer(
            msg.data,
            dtype=np.float32,
        ).reshape(msg.height, stride)

        return arr[:, : msg.width].copy()

    raise RuntimeError(
        f"Unsupported depth encoding: {msg.encoding}"
    )


def find_obstacles(meters):
    in_range = (
        np.isfinite(meters)
        & (meters >= 0.4)
        & (meters <= 1.6)
    )

    mask = (in_range.astype(np.uint8) * 255)
    mask = cv2.medianBlur(mask, 5)

    kernel = np.ones((3, 3), dtype=np.uint8)
    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_OPEN,
        kernel,
    )

    # ?곷떒 ?곹깭 諛??곸뿭? ?꾨낫?먯꽌 ?쒖쇅?쒕떎.
    mask[: min(50, mask.shape[0]), :] = 0

    count, labels, stats, _ = (
        cv2.connectedComponentsWithStats(
            mask,
            connectivity=8,
        )
    )

    min_area = max(120, int(meters.size * 0.001))
    obstacles = []

    for index in range(1, count):
        x, y, w, h, area = stats[index]

        if area < min_area or w < 10 or h < 10:
            continue

        values = meters[labels == index]

        obstacles.append({
            "x": int(x),
            "y": int(y),
            "w": int(w),
            "h": int(h),
            "distance": float(np.median(values)),
        })

    obstacles.sort(
        key=lambda item: item["distance"]
    )

    return obstacles


def depth_visual(depth):
    if depth.dtype == np.uint16:
        meters = depth.astype(np.float32) / 1000.0
    else:
        meters = depth.astype(np.float32)

    obstacles = find_obstacles(meters)

    valid = (
        np.isfinite(meters)
        & (meters > 0.05)
        & (meters < 10.0)
    )

    near = 0.3
    far = 6.0

    clipped = np.clip(meters, near, far)

    normalized = (
        (far - clipped)
        / (far - near)
        * 255.0
    ).astype(np.uint8)

    output = cv2.applyColorMap(
        normalized,
        cv2.COLORMAP_TURBO,
    )

    output[~valid] = (18, 20, 22)

    cv2.rectangle(
        output,
        (0, 0),
        (output.shape[1], 50),
        (18, 20, 22),
        -1,
    )

    cv2.putText(
        output,
        "DEPTH CAMERA  |  LIVE",
        (18, 31),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (245, 245, 245),
        2,
        cv2.LINE_AA,
    )

    cy = meters.shape[0] // 2
    cx = meters.shape[1] // 2

    region = meters[
        max(0, cy - 10): min(meters.shape[0], cy + 11),
        max(0, cx - 10): min(meters.shape[1], cx + 11),
    ]

    region_valid = (
        np.isfinite(region)
        & (region > 0.05)
        & (region < 10.0)
    )

    if np.any(region_valid):
        distance = float(
            np.median(region[region_valid])
        )

        cv2.rectangle(
            output,
            (cx - 65, cy - 30),
            (cx + 65, cy + 30),
            (255, 255, 255),
            1,
        )

        cv2.putText(
            output,
            f"{distance:.2f} m",
            (cx - 42, cy + 7),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.62,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )

    for obstacle in obstacles:
        x = obstacle["x"]
        y = obstacle["y"]
        x2 = min(
            output.shape[1] - 1,
            x + obstacle["w"],
        )
        y2 = min(
            output.shape[0] - 1,
            y + obstacle["h"],
        )

        cv2.rectangle(
            output,
            (x, y),
            (x2, y2),
            (0, 0, 255),
            3,
        )

        label = (
            f"OBSTACLE {obstacle['distance']:.2f} m"
        )
        (label_width, _), _ = cv2.getTextSize(
            label,
            cv2.FONT_HERSHEY_SIMPLEX,
            0.58,
            2,
        )
        label_x = min(
            x + 4,
            max(4, output.shape[1] - label_width - 4),
        )
        label_y = max(70, y - 8)

        cv2.putText(
            output,
            label,
            (label_x, label_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.58,
            (0, 0, 255),
            2,
            cv2.LINE_AA,
        )

    return output, obstacles


class VisionNode(Node):
    def __init__(
        self,
        rgb_topic,
        depth_topic,
        model,
        score_threshold,
    ):
        super().__init__("ai_rescue_demo_vision")

        base_options = python.BaseOptions(
            model_asset_path=model,
        )

        options = vision.ObjectDetectorOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.IMAGE,
            max_results=8,
            score_threshold=score_threshold,
        )

        self.detector = (
            vision.ObjectDetector.create_from_options(
                options
            )
        )

        self.persons = []

        self.last_rgb = 0.0
        self.last_depth = 0.0
        self.last_detect = 0.0

        self.create_subscription(
            Image,
            rgb_topic,
            self.on_rgb,
            qos_profile_sensor_data,
        )

        self.create_subscription(
            Image,
            depth_topic,
            self.on_depth,
            qos_profile_sensor_data,
        )

        self.get_logger().info(
            f"RGB   : {rgb_topic}"
        )
        self.get_logger().info(
            f"Depth : {depth_topic}"
        )
        self.get_logger().info(
            f"Model : {model}"
        )

    def detect(self, bgr):
        rgb = cv2.cvtColor(
            bgr,
            cv2.COLOR_BGR2RGB,
        )

        mp_image = mp.Image(
            image_format=mp.ImageFormat.SRGB,
            data=np.ascontiguousarray(rgb),
        )

        result = self.detector.detect(mp_image)

        persons = []

        for detection in result.detections:
            if not detection.categories:
                continue

            category = detection.categories[0]

            name = (
                category.category_name
                or category.display_name
                or ""
            ).lower()

            if name != "person":
                continue

            box = detection.bounding_box

            persons.append({
                "x": int(box.origin_x),
                "y": int(box.origin_y),
                "w": int(box.width),
                "h": int(box.height),
                "score": float(category.score),
            })

        persons.sort(
            key=lambda x: x["score"],
            reverse=True,
        )

        return persons

    def on_rgb(self, msg):
        global RGB_JPEG

        now = time.monotonic()

        # ??4 FPS留??쒓컖?뷀빐??SLAM 遺?섎? 以꾩씤??
        if now - self.last_rgb < 0.25:
            return

        self.last_rgb = now

        try:
            image = rgb_msg_to_bgr(msg)

            # MediaPipe 異붾줎? ??2 FPS
            if now - self.last_detect >= 0.5:
                self.last_detect = now
                self.persons = self.detect(image)

            output = image.copy()

            cv2.rectangle(
                output,
                (0, 0),
                (output.shape[1], 50),
                (18, 20, 22),
                -1,
            )

            cv2.putText(
                output,
                "MEDIAPIPE PERSON DETECTION  |  LIVE",
                (18, 31),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.64,
                (245, 245, 245),
                2,
                cv2.LINE_AA,
            )

            for person in self.persons:
                x = max(0, person["x"])
                y = max(0, person["y"])

                x2 = min(
                    output.shape[1] - 1,
                    x + person["w"],
                )

                y2 = min(
                    output.shape[0] - 1,
                    y + person["h"],
                )

                score = person["score"]

                cv2.rectangle(
                    output,
                    (x, y),
                    (x2, y2),
                    (0, 220, 110),
                    3,
                )

                label = (
                    f"PERSON {score * 100:.1f}%"
                )

                label_y = max(55, y - 10)

                cv2.putText(
                    output,
                    label,
                    (x + 4, label_y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.58,
                    (0, 255, 140),
                    2,
                    cv2.LINE_AA,
                )

            count = len(self.persons)

            if count:
                best = self.persons[0]["score"]

                bottom = (
                    f"PERSON DETECTED  |  "
                    f"count {count}  |  "
                    f"best {best * 100:.1f}%"
                )

                color = (0, 230, 130)

            else:
                best = 0.0
                bottom = "NO PERSON DETECTED"
                color = (180, 190, 200)

            cv2.putText(
                output,
                bottom,
                (18, output.shape[0] - 20),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                color,
                2,
                cv2.LINE_AA,
            )

            jpeg = encode_jpeg(output)

            with LOCK:
                RGB_JPEG = jpeg

                STATUS["rgb_ready"] = True
                STATUS["person_count"] = count
                STATUS["confidence"] = best
                STATUS["updated_at"] = time.time()

        except Exception as exc:
            self.get_logger().warning(
                f"RGB error: {exc}"
            )

    def on_depth(self, msg):
        global DEPTH_JPEG

        now = time.monotonic()

        if now - self.last_depth < 0.25:
            return

        self.last_depth = now

        try:
            depth = depth_msg_to_array(msg)
            output, obstacles = depth_visual(depth)
            jpeg = encode_jpeg(output)

            with LOCK:
                DEPTH_JPEG = jpeg
                STATUS["depth_ready"] = True
                STATUS["obstacle_count"] = len(obstacles)
                STATUS["nearest_obstacle_m"] = (
                    obstacles[0]["distance"]
                    if obstacles
                    else None
                )

        except Exception as exc:
            self.get_logger().warning(
                f"Depth error: {exc}"
            )


class Handler(BaseHTTPRequestHandler):
    def send_payload(
        self,
        payload,
        content_type,
    ):
        self.send_response(200)
        self.send_header(
            "Content-Type",
            content_type,
        )
        self.send_header(
            "Content-Length",
            str(len(payload)),
        )
        self.send_header(
            "Cache-Control",
            "no-store, no-cache, must-revalidate",
        )
        self.send_header(
            "Access-Control-Allow-Origin",
            "*",
        )
        self.end_headers()

        self.wfile.write(payload)

    def do_GET(self):
        path = self.path.split("?", 1)[0]

        if path == "/person.jpg":
            with LOCK:
                payload = RGB_JPEG

            self.send_payload(
                payload,
                "image/jpeg",
            )
            return

        if path == "/depth.jpg":
            with LOCK:
                payload = DEPTH_JPEG

            self.send_payload(
                payload,
                "image/jpeg",
            )
            return

        if path == "/status.json":
            with LOCK:
                payload = json.dumps(
                    STATUS
                ).encode("utf-8")

            self.send_payload(
                payload,
                "application/json",
            )
            return

        payload = (
            b"AI Rescue Box Vision Server\n"
            b"/person.jpg\n"
            b"/depth.jpg\n"
            b"/status.json\n"
        )

        self.send_payload(
            payload,
            "text/plain",
        )

    def log_message(self, fmt, *args):
        return


def main():
    global RGB_JPEG
    global DEPTH_JPEG

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--rgb-topic",
        default="/camera/color/image_raw",
    )

    parser.add_argument(
        "--depth-topic",
        default="/camera/depth/image_raw",
    )

    parser.add_argument(
        "--model",
        default=(
            "/home/a/mediapipe_test/models/"
            "efficientdet_lite0.tflite"
        ),
    )

    parser.add_argument(
        "--port",
        type=int,
        default=8091,
    )

    parser.add_argument(
        "--score-threshold",
        type=float,
        default=0.40,
    )

    args = parser.parse_args()

    RGB_JPEG = placeholder(
        "PERSON DETECTION",
        "Waiting for RGB camera...",
    )

    DEPTH_JPEG = placeholder(
        "DEPTH CAMERA",
        "Waiting for depth camera...",
    )

    rclpy.init()

    node = VisionNode(
        args.rgb_topic,
        args.depth_topic,
        args.model,
        args.score_threshold,
    )

    server = ThreadingHTTPServer(
        ("0.0.0.0", args.port),
        Handler,
    )

    thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
    )

    thread.start()

    node.get_logger().info(
        f"Vision HTTP : 0.0.0.0:{args.port}"
    )

    try:
        rclpy.spin(node)

    except KeyboardInterrupt:
        pass

    finally:
        server.shutdown()
        server.server_close()

        node.destroy_node()

        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
