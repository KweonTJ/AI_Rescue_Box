"""Launch the Astra Mini camera without generating unused point clouds."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration

from d_slam.launch_helpers import make_camera_container


def _launch_setup(context, *args, **kwargs):
    camera_params_file = LaunchConfiguration("camera_params_file").perform(context)
    return [make_camera_container(camera_params_file)]


def generate_launch_description():
    default_camera_params = os.path.join(
        get_package_share_directory("d_slam"),
        "config",
        "astra_slam.yaml",
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "camera_params_file",
                default_value=default_camera_params,
                description="Flat Astra Mini parameter YAML file.",
            ),
            OpaqueFunction(function=_launch_setup),
        ]
    )
