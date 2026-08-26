"""Concrete rclpy subscriptions feeding the dependency-free d_slam providers.

All callbacks run in a ROS executor owned by :class:`RosExecutorWorker`, never
in the API event loop. Communication is intentionally not created here; UWB is
owned by ``src/uwb`` and can be attached through an application port.
"""

from __future__ import annotations

import json
import math
import os
import struct
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable, Sequence

from ..config import AppConfig
from ..domain import CameraPoint, OccupancyGrid, Point2D, Pose2D, RiskZone
from ..perception import PersonFusionEngine
from ..providers.base import CameraIntrinsics, RgbFrame
from ..risk import ConservativeSensorRiskAnalyzer, MapPoint3D
from .prior_map import PriorMapRosAdapter, build_prior_occupancy_reference
from .adapters import AstraDepthProvider, RtabmapSlamProvider


try:
    import rclpy
    from geometry_msgs.msg import PoseWithCovarianceStamped
    from nav_msgs.msg import OccupancyGrid as RosOccupancyGrid
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.node import Node
    from rclpy.qos import (
        DurabilityPolicy,
        QoSProfile,
        ReliabilityPolicy,
        qos_profile_sensor_data,
    )
    from rclpy.time import Time
    from sensor_msgs.msg import CameraInfo, CompressedImage, Image, PointCloud2
    from std_msgs.msg import String
    from tf2_ros import Buffer, TransformListener
except ImportError:
    rclpy = None
    MultiThreadedExecutor = None
    Node = object
    PoseWithCovarianceStamped = RosOccupancyGrid = CameraInfo = CompressedImage = Image = PointCloud2 = None
    Buffer = TransformListener = None
    Time = None
    String = None
    qos_profile_sensor_data = None
    DurabilityPolicy = QoSProfile = ReliabilityPolicy = None

try:
    from rtabmap_msgs.msg import Info as RtabmapInfo
except ImportError:
    RtabmapInfo = None


def ros_stamp_to_iso(stamp: Any) -> str:
    seconds = int(getattr(stamp, "sec", 0))
    nanoseconds = int(getattr(stamp, "nanosec", 0))
    return datetime.fromtimestamp(
        seconds + nanoseconds / 1_000_000_000, tz=timezone.utc
    ).isoformat().replace("+00:00", "Z")


def quaternion_yaw(quaternion: Any) -> float:
    x, y, z, w = (
        float(quaternion.x),
        float(quaternion.y),
        float(quaternion.z),
        float(quaternion.w),
    )
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def decode_depth_image(message: Any) -> tuple[list[list[float | int]], float]:
    encoding = str(message.encoding).upper()
    if encoding in {"16UC1", "MONO16"}:
        code, item_size, scale = "H", 2, 0.001
    elif encoding == "32FC1":
        code, item_size, scale = "f", 4, 1.0
    else:
        raise ValueError(f"unsupported depth encoding {message.encoding!r}")
    width, height, step = int(message.width), int(message.height), int(message.step)
    if width <= 0 or height <= 0 or step < width * item_size:
        raise ValueError("invalid depth image dimensions or row stride")
    content = memoryview(message.data)
    if len(content) < step * height:
        raise ValueError("depth image data is shorter than declared dimensions")
    byte_order = ">" if bool(message.is_bigendian) else "<"
    row_format = f"{byte_order}{width}{code}"
    rows = [
        list(struct.unpack_from(row_format, content, y * step)) for y in range(height)
    ]
    return rows, scale


def depth_image_to_camera_points(
    depth: Sequence[Sequence[float | int]],
    intrinsics: CameraIntrinsics,
    *,
    depth_scale: float,
    pixel_stride: int = 8,
    minimum_depth_m: float = 0.15,
    maximum_depth_m: float = 10.0,
    maximum_points: int = 40_000,
) -> tuple[CameraPoint, ...]:
    if depth_scale <= 0 or pixel_stride < 1 or maximum_points < 1:
        raise ValueError("invalid depth projection settings")
    if minimum_depth_m <= 0 or maximum_depth_m <= minimum_depth_m:
        raise ValueError("invalid depth measurement range")
    points: list[CameraPoint] = []
    for y in range(pixel_stride // 2, min(intrinsics.height, len(depth)), pixel_stride):
        row = depth[y]
        for x in range(pixel_stride // 2, min(intrinsics.width, len(row)), pixel_stride):
            z = float(row[x]) * depth_scale
            if not math.isfinite(z) or not minimum_depth_m <= z <= maximum_depth_m:
                continue
            points.append(
                CameraPoint(
                    (x - intrinsics.cx) * z / intrinsics.fx,
                    (y - intrinsics.cy) * z / intrinsics.fy,
                    z,
                )
            )
            if len(points) >= maximum_points:
                return tuple(points)
    return tuple(points)


_POINT_FIELD_FORMATS = {7: ("f", 4), 8: ("d", 8)}


def decode_point_cloud2(
    message: Any, *, maximum_points: int = 40_000
) -> tuple[CameraPoint, ...]:
    if maximum_points < 1:
        raise ValueError("maximum point cloud samples must be positive")
    fields = {str(field.name): field for field in message.fields}
    if not {"x", "y", "z"} <= set(fields):
        raise ValueError("PointCloud2 requires x, y and z fields")
    descriptors = []
    for name in ("x", "y", "z"):
        field = fields[name]
        if int(getattr(field, "count", 1)) != 1:
            raise ValueError(f"PointCloud2 {name} field must have count=1")
        try:
            code, size = _POINT_FIELD_FORMATS[int(field.datatype)]
        except KeyError as error:
            raise ValueError(
                f"PointCloud2 {name} field must be FLOAT32 or FLOAT64"
            ) from error
        descriptors.append((int(field.offset), code, size))
    width, height = int(message.width), int(message.height)
    point_step, row_step = int(message.point_step), int(message.row_step)
    if width <= 0 or height <= 0 or point_step <= 0 or row_step < width * point_step:
        raise ValueError("invalid PointCloud2 dimensions or stride")
    if any(offset < 0 or offset + size > point_step for offset, _, size in descriptors):
        raise ValueError("PointCloud2 field exceeds point_step")
    content = memoryview(message.data)
    if len(content) < row_step * height:
        raise ValueError("PointCloud2 data is shorter than declared dimensions")
    byte_order = ">" if bool(message.is_bigendian) else "<"
    total = width * height
    sample_stride = max(1, math.ceil(total / maximum_points))
    points: list[CameraPoint] = []
    for linear_index in range(0, total, sample_stride):
        row, column = divmod(linear_index, width)
        base = row * row_step + column * point_step
        values = [
            float(struct.unpack_from(byte_order + code, content, base + offset)[0])
            for offset, code, _ in descriptors
        ]
        if all(math.isfinite(value) for value in values):
            points.append(CameraPoint(*values))
    return tuple(points)


def transform_camera_point(point: CameraPoint, transform: Any) -> MapPoint3D:
    q, translation = transform.rotation, transform.translation
    vx, vy, vz = point.x, point.y, point.z
    tx = 2.0 * (q.y * vz - q.z * vy)
    ty = 2.0 * (q.z * vx - q.x * vz)
    tz = 2.0 * (q.x * vy - q.y * vx)
    return MapPoint3D(
        vx + q.w * tx + (q.y * tz - q.z * ty) + float(translation.x),
        vy + q.w * ty + (q.z * tx - q.x * tz) + float(translation.y),
        vz + q.w * tz + (q.x * ty - q.y * tx) + float(translation.z),
    )


def _component_bounds(
    grid: OccupancyGrid, value_test: Callable[[int], bool]
) -> tuple[tuple[Point2D, ...], ...]:
    remaining = {
        (x, y)
        for y in range(grid.height)
        for x in range(grid.width)
        if value_test(grid.value(x, y))
    }
    polygons = []
    while remaining:
        first = min(remaining, key=lambda cell: (cell[1], cell[0]))
        remaining.remove(first)
        stack, cells = [first], []
        while stack:
            x, y = stack.pop()
            cells.append((x, y))
            for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    stack.append(neighbor)
        min_x, max_x = min(x for x, _ in cells), max(x for x, _ in cells) + 1
        min_y, max_y = min(y for _, y in cells), max(y for _, y in cells) + 1
        ox, oy, size = grid.origin.x, grid.origin.y, grid.resolution
        polygons.append(
            (
                Point2D(ox + min_x * size, oy + min_y * size),
                Point2D(ox + max_x * size, oy + min_y * size),
                Point2D(ox + max_x * size, oy + max_y * size),
                Point2D(ox + min_x * size, oy + max_y * size),
            )
        )
    return tuple(polygons)


class SensorRosNode(Node):
    """Concrete configurable ROS subscriber node for real sensor mode."""

    def __init__(
        self,
        config: AppConfig,
        slam: RtabmapSlamProvider,
        depth: AstraDepthProvider,
        *,
        fusion: PersonFusionEngine | None = None,
        candidate_callback: Callable[[Sequence[Any]], None] | None = None,
        point_cloud_callback: Callable[[Any], None] | None = None,
    ) -> None:
        if rclpy is None or RosOccupancyGrid is None:
            raise RuntimeError("ROS 2 Python packages are unavailable")
        super().__init__("ai_rescue_jetson_sensor_adapter")
        self.config = config
        self.slam = slam
        self.depth = depth
        self.fusion = fusion
        self.candidate_callback = candidate_callback
        self.point_cloud_callback = point_cloud_callback
        self._state_lock = threading.RLock()
        self._latest_grid: OccupancyGrid | None = None
        self._latest_pose: Pose2D | None = None
        self._trajectory: deque[Pose2D] = deque(maxlen=10000)
        self._tracking_status = (
            "waiting_for_rtabmap" if RtabmapInfo is not None else "rtabmap_msgs_unavailable"
        )
        self._map_version = 0
        self._intrinsics: CameraIntrinsics | None = None
        self._last_point_cloud: Any | None = None
        self._last_rgb: Any | None = None
        self._sensor_risk_analyzer = ConservativeSensorRiskAnalyzer(
            cell_size_m=config.sensor_risk_cell_size_m,
            minimum_points_per_cell=config.sensor_risk_min_points_per_cell,
            debris_minimum_points=config.sensor_risk_debris_minimum_points,
            debris_height_spread_m=config.sensor_risk_debris_spread_m,
            step_height_threshold_m=config.sensor_risk_step_height_m,
            drop_height_threshold_m=config.sensor_risk_drop_height_m,
            maximum_points=config.sensor_risk_maximum_points,
        )
        self._sensor_risks: dict[str, tuple[RiskZone, ...]] = {}
        self._mission_epoch = 0
        self._inference_pool = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="jetson-person-inference"
        )
        self._inference_pending = threading.Event()
        self._person_inference_interval_s = max(
            0.0,
            float(os.environ.get("AI_RESCUE_PERSON_INFERENCE_INTERVAL_S", "1.0")),
        )
        self._last_person_inference_monotonic = float("-inf")
        qos_state = 10
        qos_sensor = qos_profile_sensor_data

        # RTAB-Map occupancy grid is a latched TRANSIENT_LOCAL topic.
        # Match its QoS so a restarted Jetson API immediately receives
        # the latest map instead of waiting for a future publication.
        qos_map = QoSProfile(depth=1)
        qos_map.reliability = ReliabilityPolicy.RELIABLE
        qos_map.durability = DurabilityPolicy.TRANSIENT_LOCAL

        self.create_subscription(
            RosOccupancyGrid,
            config.topics.occupancy_grid,
            self._on_occupancy,
            qos_map,
        )
        self.create_subscription(
            PoseWithCovarianceStamped,
            config.topics.robot_pose,
            self._on_pose,
            qos_state,
        )
        self.create_subscription(Image, config.topics.rgb, self._on_rgb, qos_sensor)

        self._external_person_topic = os.environ.get(
            "AI_RESCUE_EXTERNAL_PERSON_TOPIC", ""
        ).strip()

        self._external_person_subscription = None

        if self._external_person_topic and String is not None:
            self._external_person_subscription = self.create_subscription(
                String,
                self._external_person_topic,
                self._on_external_person_detections,
                qos_state,
            )

            self.get_logger().warning(
                "external person detector enabled: "
                + self._external_person_topic
            )
        self.create_subscription(Image, config.topics.depth, self._on_depth, qos_sensor)
        self.create_subscription(
            CameraInfo, config.topics.camera_info, self._on_camera_info, qos_sensor
        )
        if config.topics.point_cloud:
            self.create_subscription(
                PointCloud2,
                config.topics.point_cloud,
                self._on_point_cloud,
                qos_sensor,
            )
        if RtabmapInfo is not None and config.topics.rtabmap_status:
            self.create_subscription(
                RtabmapInfo,
                config.topics.rtabmap_status,
                self._on_rtabmap_info,
                qos_state,
            )
        else:
            self.get_logger().warning(
                "rtabmap_msgs is unavailable; RTAB status subscription is disabled"
            )
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self, spin_thread=False)
        prior_qos = QoSProfile(depth=1)
        prior_qos.reliability = ReliabilityPolicy.RELIABLE
        prior_qos.durability = DurabilityPolicy.TRANSIENT_LOCAL
        self._prior_map_publisher = (
            self.create_publisher(CompressedImage, config.topics.prior_map, prior_qos)
            if config.prior_map_publish_enabled
            else None
        )
        self._prior_occupancy_publisher = (
            self.create_publisher(RosOccupancyGrid, config.topics.prior_occupancy, prior_qos)
            if config.prior_map_publish_enabled
            else None
        )
        self._initial_pose_publisher = (
            self.create_publisher(PoseWithCovarianceStamped, config.topics.initial_pose, prior_qos)
            if config.initial_pose_publish_enabled
            else None
        )
        self.prior_map_adapter = PriorMapRosAdapter(
            publish_reference=(
                self._publish_prior_reference
                if self._prior_map_publisher is not None
                else None
            ),
            publish_initial_pose=(
                self._publish_initial_pose
                if self._initial_pose_publisher is not None
                else None
            ),
        )

    def _publish_prior_reference(
        self, image: bytes, image_format: str, manifest: Any
    ) -> None:
        message = CompressedImage()
        message.header.stamp = self.get_clock().now().to_msg()
        message.header.frame_id = str(manifest.get("coordinate_frame", "map"))
        message.format = image_format
        message.data = image
        self._prior_map_publisher.publish(message)
        occupancy_published = False
        try:
            occupancy = build_prior_occupancy_reference(
                image,
                manifest,
                dark_pixel_threshold=self.config.prior_map_dark_pixel_threshold,
            )
            grid = RosOccupancyGrid()
            grid.header.stamp = message.header.stamp
            grid.header.frame_id = occupancy.frame_id
            grid.info.width = occupancy.width
            grid.info.height = occupancy.height
            grid.info.resolution = occupancy.resolution
            grid.info.origin.position.x = occupancy.origin_x
            grid.info.origin.position.y = occupancy.origin_y
            grid.info.origin.orientation.z = math.sin(occupancy.origin_yaw / 2.0)
            grid.info.origin.orientation.w = math.cos(occupancy.origin_yaw / 2.0)
            grid.data = list(occupancy.data)
            self._prior_occupancy_publisher.publish(grid)
            occupancy_published = True
        except ValueError as error:
            self.get_logger().warning(
                f"prior occupancy reference is unavailable: {error}"
            )
        self.get_logger().warning(
            "published verified mission image"
            + (
                " and conservative prior occupancy (dark=occupied, all other pixels=unknown)"
                if occupancy_published
                else ""
            )
            + " as references only; it is not an RTAB-Map database or confirmed alignment"
        )

    def _publish_initial_pose(self, pose: Pose2D, frame_id: str) -> None:
        message = PoseWithCovarianceStamped()
        message.header.stamp = self.get_clock().now().to_msg()
        message.header.frame_id = frame_id
        message.pose.pose.position.x = pose.x
        message.pose.pose.position.y = pose.y
        message.pose.pose.orientation.z = math.sin(pose.yaw / 2.0)
        message.pose.pose.orientation.w = math.cos(pose.yaw / 2.0)
        message.pose.covariance[0] = 0.25
        message.pose.covariance[7] = 0.25
        message.pose.covariance[35] = math.radians(15.0) ** 2
        self._initial_pose_publisher.publish(message)

    def _on_external_person_detections(self, message: Any) -> None:
        fusion = self.fusion

        if fusion is None:
            return

        updater = getattr(
            fusion.detector,
            "update_json",
            None,
        )

        if not callable(updater):
            return

        try:
            updater(str(message.data))

        except Exception as error:
            self.get_logger().warning(
                f"discarding external person detections: {error}"
            )

    def _on_camera_info(self, message: Any) -> None:
        k = message.k
        try:
            self._intrinsics = CameraIntrinsics(
                int(message.width),
                int(message.height),
                float(k[0]),
                float(k[4]),
                float(k[2]),
                float(k[5]),
                str(message.header.frame_id or "camera_depth_optical_frame"),
            )
        except (IndexError, TypeError, ValueError) as error:
            self._intrinsics = None
            self.depth.reset()
            with self._state_lock:
                self._sensor_risks.pop("registered_depth", None)
            self._update_slam()
            self.get_logger().warning(f"discarding invalid CameraInfo: {error}")

    def _on_depth(self, message: Any) -> None:
        if self._intrinsics is None:
            return
        try:
            if (
                int(message.width) != self._intrinsics.width
                or int(message.height) != self._intrinsics.height
            ):
                raise ValueError("registered depth dimensions do not match CameraInfo")
            depth_frame = str(message.header.frame_id or "")
            if depth_frame and depth_frame != self._intrinsics.frame_id:
                raise ValueError("registered depth frame does not match CameraInfo frame")
            values, scale = decode_depth_image(message)
            self.depth.update_depth(
                values,
                self._intrinsics,
                depth_scale=scale,
                timestamp=ros_stamp_to_iso(message.header.stamp),
            )
            points = depth_image_to_camera_points(
                values,
                self._intrinsics,
                depth_scale=scale,
                pixel_stride=self.config.sensor_risk_depth_pixel_stride,
                minimum_depth_m=self.depth.minimum_depth_m,
                maximum_depth_m=self.depth.maximum_depth_m,
                maximum_points=self.config.sensor_risk_maximum_points,
            )
            self._update_sensor_risks(
                "registered_depth",
                points,
                source_frame=depth_frame or self._intrinsics.frame_id,
                observed_at=ros_stamp_to_iso(message.header.stamp),
            )
        except (ValueError, struct.error) as error:
            self.depth.reset()
            with self._state_lock:
                self._sensor_risks.pop("registered_depth", None)
            self._update_slam()
            self.get_logger().warning(f"discarding invalid depth image: {error}")

    def _on_rgb(self, message: Any) -> None:
        self._last_rgb = message
        if self.fusion is None or self._inference_pending.is_set():
            return
        now = time.monotonic()
        if (
            now - self._last_person_inference_monotonic
            < self._person_inference_interval_s
        ):
            return
        self._last_person_inference_monotonic = now
        self._inference_pending.set()
        with self._state_lock:
            mission_epoch = self._mission_epoch
        timestamp = ros_stamp_to_iso(message.header.stamp)
        frame = RgbFrame(
            int(message.width),
            int(message.height),
            message,
            str(message.encoding),
            str(message.header.frame_id),
            timestamp,
        )
        future = self._inference_pool.submit(self.fusion.process, frame)

        def complete(completed: Any) -> None:
            try:
                candidates = completed.result()
                with self._state_lock:
                    if mission_epoch != self._mission_epoch:
                        if self.fusion is not None:
                            self.fusion.reset()
                        return
                    log_counts = getattr(
                        self,
                        "_candidate_log_counts",
                        {},
                    )

                    for candidate in candidates:
                        previous = log_counts.get(
                            candidate.detection_id,
                            0,
                        )

                        if candidate.observation_count <= previous:
                            continue

                        log_counts[candidate.detection_id] = (
                            candidate.observation_count
                        )

                        camera = candidate.camera_position
                        mapped = candidate.map_position

                        camera_text = (
                            f"({camera.x:.2f},"
                            f"{camera.y:.2f},"
                            f"{camera.z:.2f})"
                            if camera is not None
                            else "None"
                        )

                        map_text = (
                            f"({mapped.x:.2f},"
                            f"{mapped.y:.2f})"
                            if mapped is not None
                            else "None"
                        )

                        self.get_logger().info(
                            "person candidate "
                            f"source={candidate.source} "
                            f"confidence={candidate.confidence:.3f} "
                            f"observations={candidate.observation_count} "
                            f"camera_xyz={camera_text} "
                            f"slam_map_xy={map_text}"
                        )

                    self._candidate_log_counts = log_counts

                    if self.candidate_callback is not None:
                        self.candidate_callback(candidates)
            except Exception as error:
                self.get_logger().error(f"person inference failed: {error}")
            finally:
                self._inference_pending.clear()

        future.add_done_callback(complete)

    def _on_point_cloud(self, message: Any) -> None:
        with self._state_lock:
            self._last_point_cloud = message
        try:
            points = decode_point_cloud2(
                message, maximum_points=self.config.sensor_risk_maximum_points
            )
            self._update_sensor_risks(
                "pointcloud2",
                points,
                source_frame=str(message.header.frame_id),
                observed_at=ros_stamp_to_iso(message.header.stamp),
            )
        except (ValueError, struct.error) as error:
            with self._state_lock:
                self._sensor_risks.pop("pointcloud2", None)
            self._update_slam()
            self.get_logger().warning(f"discarding invalid point cloud: {error}")
        if self.point_cloud_callback is not None:
            self.point_cloud_callback(message)

    @property
    def last_point_cloud(self) -> Any | None:
        with self._state_lock:
            return self._last_point_cloud

    def _on_pose(self, message: Any) -> None:
        pose = message.pose.pose
        with self._state_lock:
            self._latest_pose = Pose2D(
                float(pose.position.x),
                float(pose.position.y),
                quaternion_yaw(pose.orientation),
            )
            if not self._trajectory or self._trajectory[-1] != self._latest_pose:
                self._trajectory.append(self._latest_pose)
        self._update_slam()

    def _on_occupancy(self, message: Any) -> None:
        try:
            with self._state_lock:
                self._latest_grid = RtabmapSlamProvider.occupancy_from_ros(message)
                self._map_version += 1
            self._update_slam()
        except (ValueError, TypeError) as error:
            self.get_logger().warning(f"discarding invalid occupancy grid: {error}")

    def _on_rtabmap_info(self, message: Any) -> None:
        with self._state_lock:
            self._tracking_status = "tracking"
        self._update_slam()

    def _update_slam(self) -> None:
        with self._state_lock:
            if self._latest_grid is None or self._latest_pose is None:
                return
            grid = self._latest_grid
            pose = self._latest_pose
            trajectory = tuple(self._trajectory)
            tracking_status = self._tracking_status
            map_version = max(1, self._map_version)
            sensor_risks = tuple(
                risk
                for source in sorted(self._sensor_risks)
                for risk in self._sensor_risks[source]
            )
        self.slam.update(
            occupancy_grid=grid,
            robot_pose=pose,
            trajectory=trajectory,
            explored_areas=_component_bounds(grid, lambda value: value >= 0),
            unknown_areas=_component_bounds(grid, lambda value: value == -1),
            tracking_status=tracking_status,
            map_version=map_version,
            sensor_risks=sensor_risks,
        )

    def _lookup_transform(
        self, source_frame: str, target_frame: str, timestamp: str | None
    ) -> Any | None:
        if not source_frame:
            self.get_logger().warning("sensor evidence has no source frame")
            return None
        if source_frame == target_frame:
            return "identity"
        try:
            query_time = Time()
            if timestamp:
                parsed = datetime.fromisoformat(
                    timestamp[:-1] + "+00:00" if timestamp.endswith("Z") else timestamp
                )
                query_time = Time(
                    nanoseconds=int(parsed.timestamp() * 1_000_000_000)
                )
            return self.tf_buffer.lookup_transform(
                target_frame, source_frame, query_time
            ).transform
        except Exception as error:
            self.get_logger().warning(f"TF lookup failed: {error}")
            return None

    def _update_sensor_risks(
        self,
        source_key: str,
        points: Sequence[CameraPoint],
        *,
        source_frame: str,
        observed_at: str,
    ) -> None:
        with self._state_lock:
            target_frame = (
                self._latest_grid.frame_id if self._latest_grid is not None else "map"
            )
            map_version = max(1, self._map_version)
        transform = self._lookup_transform(source_frame, target_frame, observed_at)
        if transform is None:
            with self._state_lock:
                self._sensor_risks.pop(source_key, None)
            self._update_slam()
            return
        if transform == "identity":
            map_points = tuple(MapPoint3D(point.x, point.y, point.z) for point in points)
        else:
            map_points = tuple(
                transform_camera_point(point, transform) for point in points
            )
        risks = self._sensor_risk_analyzer.analyze(
            map_points,
            source=f"{source_key}_map_frame",
            observed_at=observed_at,
            map_version=map_version,
        )
        with self._state_lock:
            self._sensor_risks[source_key] = risks
        self._update_slam()

    def camera_to_map(
        self,
        point: CameraPoint,
        source_frame: str,
        target_frame: str = "map",
        timestamp: str | None = None,
    ) -> Point2D | None:
        transform = self._lookup_transform(source_frame, target_frame, timestamp)
        if transform is None:
            return None
        if transform == "identity":
            return Point2D(point.x, point.y)
        mapped = transform_camera_point(point, transform)
        return Point2D(mapped.x, mapped.y)

    def reset_mission_state(self) -> None:
        with self._state_lock:
            self._mission_epoch += 1
            self._latest_grid = None
            self._latest_pose = None
            self._trajectory.clear()
            self._tracking_status = (
                "waiting_for_rtabmap" if RtabmapInfo is not None else "rtabmap_msgs_unavailable"
            )
            self._map_version = 0
            self._intrinsics = None
            self._last_point_cloud = None
            self._last_rgb = None
            self._sensor_risks.clear()
        self.depth.reset()
        if self.fusion is not None:
            self.fusion.reset()
        self.slam.reset()
        if self.candidate_callback is not None:
            self.candidate_callback(())

    def destroy_node(self) -> bool:
        self._inference_pool.shutdown(wait=False, cancel_futures=True)
        return super().destroy_node()


class RosExecutorWorker:
    """Lifecycle wrapper for a ROS executor running outside API worker threads."""

    def __init__(self, node: Any, *, own_context: bool = False) -> None:
        if MultiThreadedExecutor is None:
            raise RuntimeError("rclpy executor is unavailable")
        self.node = node
        self.own_context = own_context
        self.executor = MultiThreadedExecutor(num_threads=3)
        self.executor.add_node(node)
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self.executor.spin,
            name="jetson-ros-executor",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self.executor.shutdown(timeout_sec=2.0)
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self.executor.remove_node(self.node)
        self.node.destroy_node()


def create_real_sensor_runtime(
    config: AppConfig,
    *,
    fusion_factory: Callable[[SensorRosNode, AstraDepthProvider], PersonFusionEngine | None]
    | None = None,
    candidate_callback: Callable[[Sequence[Any]], None] | None = None,
    point_cloud_callback: Callable[[Any], None] | None = None,
) -> tuple[RosExecutorWorker, SensorRosNode, RtabmapSlamProvider, AstraDepthProvider]:
    """Create only the d_slam sensor runtime; communication is composed elsewhere."""

    os.environ.setdefault("ROS_LOCALHOST_ONLY", "1")
    if rclpy is None:
        raise RuntimeError("ROS 2 rclpy is unavailable")
    if not rclpy.ok():
        rclpy.init(args=None)
    slam, depth = RtabmapSlamProvider(), AstraDepthProvider()
    node = SensorRosNode(
        config,
        slam,
        depth,
        candidate_callback=candidate_callback,
        point_cloud_callback=point_cloud_callback,
    )
    if fusion_factory is not None:
        node.fusion = fusion_factory(node, depth)
    return RosExecutorWorker(node), node, slam, depth


__all__ = [
    "RosExecutorWorker",
    "SensorRosNode",
    "create_real_sensor_runtime",
    "decode_depth_image",
    "decode_point_cloud2",
    "depth_image_to_camera_points",
    "quaternion_yaw",
    "ros_stamp_to_iso",
    "transform_camera_point",
]
