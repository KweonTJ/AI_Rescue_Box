import os

from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource

from launch_ros.actions import ComposableNodeContainer
from launch_ros.descriptions import ComposableNode

from ament_index_python.packages import get_package_share_directory


def generate_launch_description():

    # ---------------------------------------------------------
    # Astra
    # ---------------------------------------------------------
    astra_launch = os.path.join(
        get_package_share_directory("astra_camera"),
        "launch",
        "astra_mini.launch.py",
    )

    astra = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(astra_launch),
    )

    # ---------------------------------------------------------
    # RTAB-Map
    #
    # Astra RGB-D 영상으로 odom -> camera_link 생성
    # map -> odom 은 RTAB-Map SLAM이 생성
    # ---------------------------------------------------------
    rtabmap_launch = os.path.join(
        get_package_share_directory("rtabmap_launch"),
        "launch",
        "rtabmap.launch.py",
    )

    rtabmap = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(rtabmap_launch),
        launch_arguments={
            "frame_id": "camera_link",

            "rgb_topic": "/camera/color/image_raw",
            "depth_topic": "/camera/depth/image_raw",
            "camera_info_topic": "/camera/color/camera_info",

            "visual_odometry": "true",
            "publish_tf_odom": "true",

            "odom_topic": "odom",
            "map_frame_id": "map",

            # Astra RGB/depth timestamp 차이 허용
            "approx_sync": "true",
            "approx_sync_max_interval": "0.05",

            # Astra sensor-data QoS
            "qos": "2",

            "rtabmap_viz": "false",
            "rviz": "false",

            # 실험 시작 때 기존 DB 제거
            "rtabmap_args": "--delete_db_on_start",
        }.items(),
    )

    # ---------------------------------------------------------
    # NVIDIA nvblox
    #
    # RTAB-Map이 만든 odom TF + Astra depth를 사용해서
    # GPU 기반 TSDF / Mesh 생성
    # ---------------------------------------------------------
    nvblox = ComposableNodeContainer(
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
                    {
                        "num_cameras": 1,

                        "use_depth": True,
                        "use_color": False,
                        "use_lidar": False,

                        "use_tf_transforms": True,
                        "use_topic_transforms": False,

                        # RTAB-Map visual odometry 기준
                        "global_frame": "odom",

                        "mapping_type": "static_tsdf",

                        # 5 cm voxel
                        "voxel_size": 0.05,

                        # 전체 실험공간을 남기기 위해 자동 삭제 OFF
                        "map_clearing_radius_m": -1.0,

                        "integrate_depth_rate_hz": 30.0,
                        "update_mesh_rate_hz": 5.0,
                        "update_esdf_rate_hz": 5.0,

                        "input_qos": "SENSOR_DATA",

                        "print_rates_to_console": True,
                        "print_timings_to_console": False,
                    }
                ],

                remappings=[
                    (
                        "camera_0/depth/image",
                        "/camera/depth/image_raw",
                    ),
                    (
                        "camera_0/depth/camera_info",
                        "/camera/depth/camera_info",
                    ),
                ],
            )
        ],
    )

    return LaunchDescription([
        astra,
        rtabmap,
        nvblox,
    ])
