"""Launch handheld RTAB-Map SLAM with a rate-limited local nvblox map."""

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

from d_slam.launch_helpers import as_bool, make_nvblox_container


def _launch_setup(context, *args, **kwargs):
    return [
        make_nvblox_container(
            params_file=LaunchConfiguration("nvblox_params_file").perform(context),
            global_frame=LaunchConfiguration("nvblox_global_frame").perform(context),
            depth_topic=LaunchConfiguration("depth_topic").perform(context),
            depth_camera_info_topic=LaunchConfiguration(
                "depth_camera_info_topic"
            ).perform(context),
            use_sim_time=as_bool(
                LaunchConfiguration("use_sim_time").perform(context)
            ),
        )
    ]


def generate_launch_description():
    package_share = get_package_share_directory("d_slam")
    slam_launch = os.path.join(package_share, "launch", "d_slam.launch.py")
    default_nvblox_params = os.path.join(package_share, "config", "nvblox.yaml")

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "nvblox_params_file", default_value=default_nvblox_params
            ),
            DeclareLaunchArgument("nvblox_global_frame", default_value="odom"),
            DeclareLaunchArgument(
                "depth_topic", default_value="/camera/depth/image_raw"
            ),
            DeclareLaunchArgument(
                "depth_camera_info_topic",
                default_value="/camera/color/camera_info",
            ),
            DeclareLaunchArgument("use_sim_time", default_value="false"),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(slam_launch),
                launch_arguments={
                    "depth_topic": LaunchConfiguration("depth_topic"),
                    "use_sim_time": LaunchConfiguration("use_sim_time"),
                }.items(),
            ),
            OpaqueFunction(function=_launch_setup),
        ]
    )
