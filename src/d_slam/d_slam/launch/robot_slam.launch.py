"""Robot mode: Astra RGB-D + external fused odometry + optional nvblox."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription,
    OpaqueFunction,
)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration

from d_slam.launch_helpers import (
    as_bool,
    make_nvblox_container,
    make_rgbd_sync_node,
    make_rtabmap_node,
)


def _launch_setup(context, *args, **kwargs):
    params_file = LaunchConfiguration("params_file").perform(context)
    use_sim_time = as_bool(LaunchConfiguration("use_sim_time").perform(context))
    log_level = LaunchConfiguration("log_level").perform(context)

    color_topic = LaunchConfiguration("color_topic").perform(context)
    depth_topic = LaunchConfiguration("depth_topic").perform(context)
    camera_info_topic = LaunchConfiguration("camera_info_topic").perform(context)
    rgbd_topic = LaunchConfiguration("rgbd_topic").perform(context)
    odom_topic = LaunchConfiguration("odom_topic").perform(context)
    odom_info_topic = LaunchConfiguration("odom_info_topic").perform(context)
    map_topic = LaunchConfiguration("map_topic").perform(context)

    actions = [
        make_rgbd_sync_node(
            params_file=params_file,
            color_topic=color_topic,
            depth_topic=depth_topic,
            camera_info_topic=camera_info_topic,
            rgbd_topic=rgbd_topic,
            use_sim_time=use_sim_time,
            log_level=log_level,
        ),
        make_rtabmap_node(
            params_file=params_file,
            frame_id=LaunchConfiguration("frame_id").perform(context),
            odom_frame_id=LaunchConfiguration("odom_frame_id").perform(context),
            map_frame_id=LaunchConfiguration("map_frame_id").perform(context),
            database_path=LaunchConfiguration("database_path").perform(context),
            rgbd_topic=rgbd_topic,
            odom_topic=odom_topic,
            odom_info_topic=odom_info_topic,
            map_topic=map_topic,
            subscribe_odom_info=False,
            publish_tf=True,
            delete_db_on_start=as_bool(
                LaunchConfiguration(
                    "delete_db_on_start"
                ).perform(context)
            ),
            approx_sync_max_interval=0.05,
            use_sim_time=use_sim_time,
            log_level=log_level,
        ),
    ]

    if as_bool(LaunchConfiguration("use_nvblox").perform(context)):
        actions.append(
            make_nvblox_container(
                params_file=LaunchConfiguration("nvblox_params_file").perform(
                    context
                ),
                global_frame=LaunchConfiguration("nvblox_global_frame").perform(
                    context
                ),
                depth_topic=depth_topic,
                depth_camera_info_topic=LaunchConfiguration(
                    "depth_camera_info_topic"
                ).perform(context),
                use_sim_time=use_sim_time,
            )
        )

    return actions


def generate_launch_description():
    package_share = get_package_share_directory("d_slam")
    camera_launch = os.path.join(package_share, "launch", "camera_only.launch.py")
    default_params = os.path.join(package_share, "config", "rtabmap.yaml")
    default_nvblox_params = os.path.join(package_share, "config", "nvblox.yaml")
    default_camera_params = os.path.join(
        package_share,
        "config",
        "astra_slam.yaml",
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument("params_file", default_value=default_params),
            DeclareLaunchArgument(
                "nvblox_params_file", default_value=default_nvblox_params
            ),
            DeclareLaunchArgument(
                "camera_params_file", default_value=default_camera_params
            ),
            DeclareLaunchArgument("frame_id", default_value="base_link"),
            DeclareLaunchArgument("odom_frame_id", default_value="odom"),
            DeclareLaunchArgument("map_frame_id", default_value="map"),
            DeclareLaunchArgument(
                "database_path",
                default_value=os.path.expanduser("~/.ros/d_slam_robot.db"),
            ),
            DeclareLaunchArgument("delete_db_on_start", default_value="true"),
            DeclareLaunchArgument("use_nvblox", default_value="false"),
            DeclareLaunchArgument("nvblox_global_frame", default_value="odom"),
            DeclareLaunchArgument("use_sim_time", default_value="false"),
            DeclareLaunchArgument("log_level", default_value="info"),
            DeclareLaunchArgument(
                "color_topic", default_value="/camera/color/image_raw"
            ),
            DeclareLaunchArgument(
                "depth_topic", default_value="/camera/depth/image_raw"
            ),
            DeclareLaunchArgument(
                "camera_info_topic", default_value="/camera/color/camera_info"
            ),
            DeclareLaunchArgument(
                "depth_camera_info_topic",
                default_value="/camera/color/camera_info",
            ),
            DeclareLaunchArgument("rgbd_topic", default_value="/d_slam/rgbd_image"),
            DeclareLaunchArgument(
                "odom_topic", default_value="/odometry/filtered"
            ),
            DeclareLaunchArgument(
                "odom_info_topic", default_value="/rtabmap/odom_info"
            ),
            DeclareLaunchArgument("map_topic", default_value="/rtabmap/map"),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(camera_launch),
                launch_arguments={
                    "camera_params_file": LaunchConfiguration("camera_params_file")
                }.items(),
            ),
            OpaqueFunction(function=_launch_setup),
        ]
    )
