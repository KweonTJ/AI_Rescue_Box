from glob import glob
import os

from setuptools import find_packages, setup

package_name = "d_slam"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        (
            "share/ament_index/resource_index/packages",
            ["resource/" + package_name],
        ),
        ("share/" + package_name, ["package.xml", "README.md"]),
        (
            os.path.join("share", package_name, "launch"),
            glob("launch/*.launch.py"),
        ),
        (
            os.path.join("share", package_name, "config"),
            glob("config/*.yaml"),
        ),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Jeong-Yun-Kim",
    maintainer_email="jeongyun061030@gmail.com",
    description=(
        "Astra RGB-D SLAM launch and diagnostics for AI Rescue Box, "
        "with RTAB-Map and optional nvblox."
    ),
    license="Apache-2.0",
    extras_require={"test": ["pytest"]},
    entry_points={
        "console_scripts": [
            "depth_monitor = d_slam.depth_monitor:main",
            "slam_monitor = d_slam.slam_monitor:main",
        ],
    },
)
