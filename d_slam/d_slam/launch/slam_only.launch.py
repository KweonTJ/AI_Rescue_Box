"""Explicit alias for RTAB-Map-only SLAM; keeps d_slam.launch.py compatible."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource


def generate_launch_description():
    launch_file = os.path.join(
        get_package_share_directory("d_slam"),
        "launch",
        "d_slam.launch.py",
    )
    return LaunchDescription(
        [IncludeLaunchDescription(PythonLaunchDescriptionSource(launch_file))]
    )
