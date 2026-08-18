"""Reusable launch helpers for the d_slam package."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from launch_ros.actions import ComposableNodeContainer, Node
from launch_ros.descriptions import ComposableNode


def as_bool(value: Any) -> bool:
    """Convert a launch argument value to a boolean."""
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def load_flat_yaml(path: str) -> dict[str, Any]:
    """Load the Astra driver's flat YAML parameter file."""
    parameter_path = Path(path).expanduser()
    if not parameter_path.is_file():
        raise RuntimeError(f"Astra parameter file does not exist: {parameter_path}")

    with parameter_path.open("r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream)

    if not isinstance(data, dict):
        raise RuntimeError(
            f"Astra parameter file must contain a YAML mapping: {parameter_path}"
        )
    return data


def make_camera_container(camera_params_file: str) -> ComposableNodeContainer:
    """Launch only the Astra camera component, without CPU-heavy point clouds."""
    return ComposableNodeContainer(
        name="astra_camera_container",
        namespace="",
        package="rclcpp_components",
        executable="component_container_mt",
        output="screen",
        composable_node_descriptions=[
            ComposableNode(
                package="astra_camera",
                plugin="astra_camera::OBCameraNodeFactory",
                name="camera",
                namespace="camera",
                parameters=[load_flat_yaml(camera_params_file)],
            )
        ],
    )


def make_rgbd_sync_node(
    *,
    params_file: str,
    color_topic: str,
    depth_topic: str,
    camera_info_topic: str,
    rgbd_topic: str,
    use_sim_time: bool,
    log_level: str,
) -> Node:
    """Create one RGB/depth synchronizer shared by odometry and SLAM."""
    return Node(
        package="rtabmap_sync",
        executable="rgbd_sync",
        name="rgbd_sync",
        output="screen",
        emulate_tty=True,
        parameters=[params_file, {"use_sim_time": use_sim_time}],
        remappings=[
            ("rgb/image", color_topic),
            ("depth/image", depth_topic),
            ("rgb/camera_info", camera_info_topic),
            ("rgbd_image", rgbd_topic),
        ],
        arguments=["--ros-args", "--log-level", log_level],
    )


def make_visual_odometry_node(
    *,
    params_file: str,
    frame_id: str,
    odom_frame_id: str,
    rgbd_topic: str,
    odom_topic: str,
    odom_info_topic: str,
    publish_tf: bool,
    use_sim_time: bool,
    log_level: str,
) -> Node:
    """Create RTAB-Map RGB-D visual odometry."""
    return Node(
        package="rtabmap_odom",
        executable="rgbd_odometry",
        name="rgbd_odometry",
        output="screen",
        emulate_tty=True,
        parameters=[
            params_file,
            {
                "frame_id": frame_id,
                "odom_frame_id": odom_frame_id,
                "publish_tf": publish_tf,
                "use_sim_time": use_sim_time,
            },
        ],
        remappings=[
            ("rgbd_image", rgbd_topic),
            ("odom", odom_topic),
            ("odom_info", odom_info_topic),
        ],
        arguments=["--ros-args", "--log-level", log_level],
    )


def make_rtabmap_node(
    *,
    params_file: str,
    frame_id: str,
    odom_frame_id: str,
    map_frame_id: str,
    database_path: str,
    rgbd_topic: str,
    odom_topic: str,
    odom_info_topic: str,
    map_topic: str,
    subscribe_odom_info: bool,
    publish_tf: bool,
    delete_db_on_start: bool,
    approx_sync_max_interval: float,
    use_sim_time: bool,
    log_level: str,
) -> Node:
    """Create the RTAB-Map graph-SLAM node."""
    application_arguments: list[str] = []
    if delete_db_on_start:
        application_arguments.append("--delete_db_on_start")
    application_arguments.extend(["--ros-args", "--log-level", log_level])

    return Node(
        package="rtabmap_slam",
        executable="rtabmap",
        name="rtabmap",
        output="screen",
        emulate_tty=True,
        parameters=[
            params_file,
            {
                "frame_id": frame_id,
                "odom_frame_id": odom_frame_id,
                "map_frame_id": map_frame_id,
                "database_path": str(Path(database_path).expanduser()),
                "subscribe_odom_info": subscribe_odom_info,
                "publish_tf": publish_tf,
                "approx_sync_max_interval": approx_sync_max_interval,
                "use_sim_time": use_sim_time,
            },
        ],
        remappings=[
            ("rgbd_image", rgbd_topic),
            ("odom", odom_topic),
            ("odom_info", odom_info_topic),
            ("map", map_topic),
        ],
        arguments=application_arguments,
    )


def make_nvblox_container(
    *,
    params_file: str,
    global_frame: str,
    depth_topic: str,
    depth_camera_info_topic: str,
    use_sim_time: bool,
) -> ComposableNodeContainer:
    """Create a lower-rate local nvblox map for obstacle and ESDF use."""
    return ComposableNodeContainer(
        name="nvblox_container",
        namespace="",
        package="rclcpp_components",
        executable="component_container_mt",
        output="screen",
        composable_node_descriptions=[
            ComposableNode(
                package="nvblox_ros",
                plugin="nvblox::NvbloxNode",
                name="nvblox_node",
                parameters=[
                    params_file,
                    {
                        "global_frame": global_frame,
                        "use_sim_time": use_sim_time,
                    },
                ],
                remappings=[
                    ("camera_0/depth/image", depth_topic),
                    ("camera_0/depth/camera_info", depth_camera_info_topic),
                ],
            )
        ],
    )
