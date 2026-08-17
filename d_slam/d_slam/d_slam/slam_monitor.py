#!/usr/bin/env python3
"""Runtime health monitor for RGB-D synchronization, odometry, and map updates."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import math
import time

from nav_msgs.msg import OccupancyGrid, Odometry
import rclpy
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
    qos_profile_sensor_data,
)
from sensor_msgs.msg import Image


@dataclass
class StreamState:
    name: str
    receive_times: deque[float] = field(default_factory=deque)
    last_receive_time: float | None = None
    last_stamp_ns: int | None = None
    total: int = 0

    def record(self, now: float, stamp_ns: int | None, window_sec: float) -> None:
        self.total += 1
        self.last_receive_time = now
        self.last_stamp_ns = stamp_ns
        self.receive_times.append(now)
        self.trim(now, window_sec)

    def trim(self, now: float, window_sec: float) -> None:
        cutoff = now - window_sec
        while self.receive_times and self.receive_times[0] < cutoff:
            self.receive_times.popleft()

    def rate(self) -> float:
        if len(self.receive_times) < 2:
            return 0.0
        elapsed = self.receive_times[-1] - self.receive_times[0]
        if elapsed <= 0.0:
            return 0.0
        return (len(self.receive_times) - 1) / elapsed

    def age(self, now: float) -> float | None:
        if self.last_receive_time is None:
            return None
        return max(0.0, now - self.last_receive_time)


class SlamMonitor(Node):
    def __init__(self) -> None:
        super().__init__("slam_monitor")

        self.declare_parameter("color_topic", "/camera/color/image_raw")
        self.declare_parameter("depth_topic", "/camera/depth/image_raw")
        self.declare_parameter("odom_topic", "/rtabmap/odom")
        self.declare_parameter("map_topic", "/rtabmap/map")
        self.declare_parameter("report_period_sec", 2.0)
        self.declare_parameter("window_sec", 5.0)
        self.declare_parameter("stale_after_sec", 2.0)

        self.window_sec = float(self.get_parameter("window_sec").value)
        self.stale_after_sec = float(self.get_parameter("stale_after_sec").value)
        report_period = float(self.get_parameter("report_period_sec").value)

        self.color = StreamState("color")
        self.depth = StreamState("depth")
        self.odom = StreamState("odom")
        self.map = StreamState("map")

        self.last_odom_latency_ms: float | None = None
        self.last_map_shape: tuple[int, int, float] | None = None

        odom_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
        )
        map_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )

        self._subscriptions = [
            self.create_subscription(
                Image,
                str(self.get_parameter("color_topic").value),
                self.on_color,
                qos_profile_sensor_data,
            ),
            self.create_subscription(
                Image,
                str(self.get_parameter("depth_topic").value),
                self.on_depth,
                qos_profile_sensor_data,
            ),
            self.create_subscription(
                Odometry,
                str(self.get_parameter("odom_topic").value),
                self.on_odom,
                odom_qos,
            ),
            self.create_subscription(
                OccupancyGrid,
                str(self.get_parameter("map_topic").value),
                self.on_map,
                map_qos,
            ),
        ]
        self.timer = self.create_timer(report_period, self.report)
        self.get_logger().info("SLAM runtime monitor started")

    @staticmethod
    def _stamp_ns(msg) -> int | None:
        stamp = msg.header.stamp
        value = int(stamp.sec) * 1_000_000_000 + int(stamp.nanosec)
        return value if value > 0 else None

    def on_color(self, msg: Image) -> None:
        now = time.monotonic()
        self.color.record(now, self._stamp_ns(msg), self.window_sec)

    def on_depth(self, msg: Image) -> None:
        now = time.monotonic()
        self.depth.record(now, self._stamp_ns(msg), self.window_sec)

    def on_odom(self, msg: Odometry) -> None:
        now = time.monotonic()
        stamp_ns = self._stamp_ns(msg)
        self.odom.record(now, stamp_ns, self.window_sec)

        if stamp_ns is None:
            self.last_odom_latency_ms = None
            return

        latency_ms = (self.get_clock().now().nanoseconds - stamp_ns) / 1_000_000.0
        self.last_odom_latency_ms = (
            latency_ms
            if math.isfinite(latency_ms) and 0.0 <= latency_ms <= 60_000.0
            else None
        )

    def on_map(self, msg: OccupancyGrid) -> None:
        now = time.monotonic()
        self.map.record(now, self._stamp_ns(msg), self.window_sec)
        self.last_map_shape = (
            int(msg.info.width),
            int(msg.info.height),
            float(msg.info.resolution),
        )

    def _stream_text(self, stream: StreamState, now: float) -> str:
        stream.trim(now, self.window_sec)
        age = stream.age(now)
        if age is None:
            return f"{stream.name}=NO_DATA"
        state = "STALE" if age > self.stale_after_sec else "OK"
        return (
            f"{stream.name}={stream.rate():.1f}Hz/{state}"
            f"({age * 1000.0:.0f}ms)"
        )

    def report(self) -> None:
        now = time.monotonic()
        streams = " | ".join(
            self._stream_text(stream, now)
            for stream in (self.color, self.depth, self.odom, self.map)
        )

        sync_text = "rgb_depth_delta=n/a"
        if self.color.last_stamp_ns is not None and self.depth.last_stamp_ns is not None:
            delta_ms = abs(self.color.last_stamp_ns - self.depth.last_stamp_ns) / 1_000_000.0
            sync_text = f"rgb_depth_delta={delta_ms:.1f}ms"

        latency_text = (
            f"odom_latency={self.last_odom_latency_ms:.1f}ms"
            if self.last_odom_latency_ms is not None
            else "odom_latency=n/a"
        )

        map_text = "map=n/a"
        if self.last_map_shape is not None:
            width, height, resolution = self.last_map_shape
            map_text = f"map={width}x{height}@{resolution:.3f}m"

        self.get_logger().info(
            f"{streams} | {sync_text} | {latency_text} | {map_text}"
        )


def main(args=None) -> None:
    rclpy.init(args=args)
    node = SlamMonitor()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
