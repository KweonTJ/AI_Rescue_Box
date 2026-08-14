#!/usr/bin/env python3

import argparse
import math
import time

import cv2
import numpy as np
import rclpy
from cv_bridge import CvBridge
from nav_msgs.msg import OccupancyGrid, Odometry
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CameraInfo, Image


PANEL_WIDTH = 640
PANEL_HEIGHT = 480


def fit_panel(image, width=PANEL_WIDTH, height=PANEL_HEIGHT, nearest=False):
    canvas = np.full((height, width, 3), 35, dtype=np.uint8)
    if image is None or image.size == 0:
        return canvas

    scale = min(width / image.shape[1], height / image.shape[0])
    target = (
        max(1, int(round(image.shape[1] * scale))),
        max(1, int(round(image.shape[0] * scale))),
    )
    interpolation = cv2.INTER_NEAREST if nearest else cv2.INTER_AREA
    resized = cv2.resize(image, target, interpolation=interpolation)
    x = (width - target[0]) // 2
    y = (height - target[1]) // 2
    canvas[y:y + target[1], x:x + target[0]] = resized
    return canvas


def add_label(panel, label):
    cv2.rectangle(panel, (0, 0), (panel.shape[1], 42), (0, 0, 0), -1)
    cv2.putText(
        panel,
        label,
        (14, 29),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.75,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )


class SlamPreviewRecorder(Node):
    def __init__(self):
        super().__init__('slam_preview_recorder')
        self.bridge = CvBridge()
        self.color = None
        self.depth = None
        self.depth_info = None
        self.grid = None
        self.odom = None
        self.color_frames = 0
        self.depth_frames = 0
        self.map_updates = 0

        map_qos = QoSProfile(depth=1)
        map_qos.reliability = ReliabilityPolicy.RELIABLE
        map_qos.durability = DurabilityPolicy.TRANSIENT_LOCAL

        self.create_subscription(
            Image,
            '/camera/color/image_raw',
            self.on_color,
            qos_profile_sensor_data,
        )
        self.create_subscription(
            Image,
            '/camera/depth/image_raw',
            self.on_depth,
            qos_profile_sensor_data,
        )
        self.create_subscription(
            CameraInfo,
            '/camera/depth/camera_info',
            self.on_depth_info,
            qos_profile_sensor_data,
        )
        self.create_subscription(
            OccupancyGrid,
            '/rtabmap/map',
            self.on_grid,
            map_qos,
        )
        self.create_subscription(
            Odometry,
            '/rtabmap/odom',
            self.on_odom,
            10,
        )

    def on_color(self, msg):
        self.color = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        self.color_frames += 1

    def on_depth(self, msg):
        self.depth = np.asarray(
            self.bridge.imgmsg_to_cv2(msg, desired_encoding='passthrough')
        ).copy()
        self.depth_frames += 1

    def on_depth_info(self, msg):
        self.depth_info = msg

    def on_grid(self, msg):
        if msg.info.width > 0 and msg.info.height > 0 and msg.data:
            self.grid = msg
            self.map_updates += 1

    def on_odom(self, msg):
        self.odom = msg

    def depth_visual(self):
        if self.depth is None:
            return None

        if self.depth.dtype == np.uint16:
            depth_mm = self.depth.astype(np.float32)
        else:
            depth_mm = self.depth.astype(np.float32) * 1000.0

        valid = np.isfinite(depth_mm) & (depth_mm > 0.0)
        clipped = np.clip(depth_mm, 300.0, 5000.0)
        normalized = ((5000.0 - clipped) * (255.0 / 4700.0)).astype(np.uint8)
        normalized[~valid] = 0
        visual = cv2.applyColorMap(normalized, cv2.COLORMAP_TURBO)
        visual[~valid] = 0
        return visual

    def rtabmap_image(self):
        if self.grid is None:
            return None

        width = int(self.grid.info.width)
        height = int(self.grid.info.height)
        data = np.asarray(self.grid.data, dtype=np.int16).reshape(height, width)
        if not np.any(data >= 0):
            return None

        image = np.full((height, width, 3), (128, 128, 128), dtype=np.uint8)
        image[data == 0] = (245, 245, 245)
        image[(data > 0) & (data < 50)] = (190, 220, 255)
        image[data >= 50] = (20, 20, 20)
        return np.flipud(image)

    def local_depth_map(self):
        if self.depth is None or self.depth_info is None:
            return None

        if self.depth.dtype == np.uint16:
            depth_m = self.depth.astype(np.float32) * 0.001
        else:
            depth_m = self.depth.astype(np.float32)

        fx = float(self.depth_info.k[0])
        cx = float(self.depth_info.k[2])
        if fx <= 0.0:
            return None

        grid_size = 600
        resolution = 0.01
        x_min = -3.0
        z_max = 6.0
        image = np.full((grid_size, grid_size, 3), (128, 128, 128), dtype=np.uint8)
        robot = (grid_size // 2, grid_size - 1)

        rows = np.arange(0, depth_m.shape[0], 16)
        cols = np.arange(0, depth_m.shape[1], 16)
        for v in rows:
            for u in cols:
                z = float(depth_m[v, u])
                if not math.isfinite(z) or z < 0.3 or z > z_max:
                    continue
                x = (u - cx) * z / fx
                gx = int((x - x_min) / resolution)
                gy = grid_size - 1 - int(z / resolution)
                if 0 <= gx < grid_size and 0 <= gy < grid_size:
                    cv2.line(image, robot, (gx, gy), (235, 235, 235), 1)

        rows = np.arange(0, depth_m.shape[0], 4)
        cols = np.arange(0, depth_m.shape[1], 4)
        for v in rows:
            for u in cols:
                z = float(depth_m[v, u])
                if not math.isfinite(z) or z < 0.3 or z > z_max:
                    continue
                x = (u - cx) * z / fx
                gx = int((x - x_min) / resolution)
                gy = grid_size - 1 - int(z / resolution)
                if 0 <= gx < grid_size and 0 <= gy < grid_size:
                    image[gy, gx] = (10, 10, 10)

        cv2.circle(image, robot, 8, (255, 100, 0), -1)
        return image

    def map_image(self):
        rtabmap = self.rtabmap_image()
        if rtabmap is not None:
            return rtabmap, 'RTAB-Map OccupancyGrid'
        return self.local_depth_map(), 'Current-view Depth Map (fallback)'

    def status_panel(self, map_source):
        panel = np.full((PANEL_HEIGHT, PANEL_WIDTH, 3), (28, 28, 28), dtype=np.uint8)
        lines = [
            ('RGB-D SLAM PREVIEW', (255, 255, 255), 0.9),
            (f'Color frames: {self.color_frames}', (220, 220, 220), 0.68),
            (f'Depth frames: {self.depth_frames}', (220, 220, 220), 0.68),
            (f'Map updates: {self.map_updates}', (220, 220, 220), 0.68),
            (f'Map source: {map_source}', (120, 220, 255), 0.58),
        ]

        if self.grid is not None:
            lines.append((
                f'Map: {self.grid.info.width}x{self.grid.info.height} '
                f'@ {self.grid.info.resolution:.3f} m/cell',
                (220, 220, 220),
                0.58,
            ))
        if self.odom is not None:
            p = self.odom.pose.pose.position
            lines.append((
                f'Odom: x={p.x:.2f} m, y={p.y:.2f} m',
                (220, 220, 220),
                0.62,
            ))

        lines.extend([
            ('WHITE: free / BLACK: occupied', (245, 245, 245), 0.55),
            ('GRAY: unknown', (170, 170, 170), 0.55),
            ('Camera is stationary.', (80, 180, 255), 0.65),
            ('Map coverage is limited to the current view.', (80, 180, 255), 0.58),
        ])

        y = 62
        for text, color, scale in lines:
            cv2.putText(
                panel,
                text,
                (28, y),
                cv2.FONT_HERSHEY_SIMPLEX,
                scale,
                color,
                2,
                cv2.LINE_AA,
            )
            y += 42
        return panel

    def render(self):
        color_panel = fit_panel(self.color)
        add_label(color_panel, 'Astra RGB')

        depth_panel = fit_panel(self.depth_visual())
        add_label(depth_panel, 'Astra Depth (0.3-5.0 m)')

        map_image, map_source = self.map_image()
        map_panel = fit_panel(map_image, nearest=True)
        add_label(map_panel, map_source)

        status_panel = self.status_panel(map_source)
        top = np.hstack((color_panel, depth_panel))
        bottom = np.hstack((map_panel, status_panel))
        return np.vstack((top, bottom)), map_panel, map_source


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('video_path')
    parser.add_argument('map_path')
    parser.add_argument('--duration', type=float, default=15.0)
    parser.add_argument('--fps', type=float, default=10.0)
    args = parser.parse_args()

    rclpy.init(args=[])
    node = SlamPreviewRecorder()

    ready_deadline = time.monotonic() + 20.0
    while time.monotonic() < ready_deadline:
        rclpy.spin_once(node, timeout_sec=0.05)
        if node.color is not None and node.depth is not None:
            break
    else:
        node.destroy_node()
        rclpy.shutdown()
        raise SystemExit('Timed out waiting for RGB and depth streams')

    writer = cv2.VideoWriter(
        args.video_path,
        cv2.VideoWriter_fourcc(*'MJPG'),
        args.fps,
        (PANEL_WIDTH * 2, PANEL_HEIGHT * 2),
        True,
    )
    if not writer.isOpened():
        node.destroy_node()
        rclpy.shutdown()
        raise SystemExit(f'Could not open video writer: {args.video_path}')

    start = time.monotonic()
    next_frame = start
    preview_frames = 0
    final_map_panel = None
    final_map_source = ''

    while time.monotonic() - start < args.duration:
        rclpy.spin_once(node, timeout_sec=0.02)
        now = time.monotonic()
        if now < next_frame:
            continue
        composite, map_panel, map_source = node.render()
        writer.write(composite)
        final_map_panel = map_panel.copy()
        final_map_source = map_source
        preview_frames += 1
        next_frame += 1.0 / args.fps

    writer.release()

    if final_map_panel is None:
        node.destroy_node()
        rclpy.shutdown()
        raise SystemExit('No map preview frame was generated')

    map_output = np.full((600, 800, 3), (28, 28, 28), dtype=np.uint8)
    cv2.putText(
        map_output,
        final_map_source,
        (24, 42),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.82,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    resized_map = fit_panel(final_map_panel, width=760, height=500, nearest=True)
    map_output[65:565, 20:780] = resized_map
    cv2.imwrite(args.map_path, map_output)

    print(f'PREVIEW_FRAMES={preview_frames}')
    print(f'COLOR_FRAMES={node.color_frames}')
    print(f'DEPTH_FRAMES={node.depth_frames}')
    print(f'MAP_UPDATES={node.map_updates}')
    print(f'MAP_SOURCE={final_map_source}')

    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
