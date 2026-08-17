#!/usr/bin/env python3
"""Lightweight rolling-rate monitor for the Astra depth stream."""

from __future__ import annotations

from collections import deque
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image


class DepthMonitor(Node):
    def __init__(self) -> None:
        super().__init__("depth_monitor")

        self.declare_parameter("depth_topic", "/camera/depth/image_raw")
        self.declare_parameter("report_period_sec", 2.0)
        self.declare_parameter("window_sec", 5.0)
        self.declare_parameter("stale_after_sec", 2.0)

        depth_topic = str(self.get_parameter("depth_topic").value)
        report_period = float(self.get_parameter("report_period_sec").value)
        self.window_sec = float(self.get_parameter("window_sec").value)
        self.stale_after_sec = float(self.get_parameter("stale_after_sec").value)

        self.receive_times: deque[float] = deque()
        self.last_receive_time: float | None = None
        self.total_frames = 0
        self.first_frame_logged = False

        self.subscription = self.create_subscription(
            Image,
            depth_topic,
            self.depth_callback,
            qos_profile_sensor_data,
        )
        self.timer = self.create_timer(report_period, self.print_status)

        self.get_logger().info(f"Depth monitor listening: {depth_topic}")

    def depth_callback(self, msg: Image) -> None:
        now = time.monotonic()
        self.total_frames += 1
        self.last_receive_time = now
        self.receive_times.append(now)
        self._trim(now)

        if not self.first_frame_logged:
            self.first_frame_logged = True
            self.get_logger().info(
                "Depth stream detected: "
                f"{msg.width}x{msg.height}, "
                f"encoding={msg.encoding}, "
                f"frame={msg.header.frame_id}"
            )

    def _trim(self, now: float) -> None:
        cutoff = now - self.window_sec
        while self.receive_times and self.receive_times[0] < cutoff:
            self.receive_times.popleft()

    def _rolling_rate(self) -> float:
        if len(self.receive_times) < 2:
            return 0.0
        elapsed = self.receive_times[-1] - self.receive_times[0]
        if elapsed <= 0.0:
            return 0.0
        return (len(self.receive_times) - 1) / elapsed

    def print_status(self) -> None:
        now = time.monotonic()
        self._trim(now)

        if self.last_receive_time is None:
            self.get_logger().warn("No depth frames received")
            return

        age = now - self.last_receive_time
        rate = self._rolling_rate()
        if age > self.stale_after_sec:
            self.get_logger().warn(
                "Depth stream stopped | "
                f"last_frame_age={age:.2f}s | total={self.total_frames}"
            )
            return

        self.get_logger().info(
            "Depth stream OK | "
            f"rolling={rate:.1f} Hz | "
            f"last_frame_age={age * 1000.0:.0f} ms | "
            f"total={self.total_frames}"
        )


def main(args=None) -> None:
    rclpy.init(args=args)
    node = DepthMonitor()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
