#!/usr/bin/env python3

import time

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image


class DepthMonitor(Node):

    def __init__(self):
        super().__init__('depth_monitor')

        self.declare_parameter(
            'depth_topic',
            '/camera/depth/image_raw'
        )

        depth_topic = self.get_parameter(
            'depth_topic'
        ).get_parameter_value().string_value

        self.last_time = None
        self.frame_count = 0
        self.start_time = time.time()

        self.subscription = self.create_subscription(
            Image,
            depth_topic,
            self.depth_callback,
            10
        )

        self.timer = self.create_timer(
            2.0,
            self.print_status
        )

        self.get_logger().info(
            f'Depth monitor listening: {depth_topic}'
        )

    def depth_callback(self, msg):

        self.frame_count += 1
        self.last_time = time.time()

        if self.frame_count == 1:
            self.get_logger().info(
                f'Depth stream detected: '
                f'{msg.width}x{msg.height}, '
                f'encoding={msg.encoding}, '
                f'frame={msg.header.frame_id}'
            )

    def print_status(self):

        elapsed = time.time() - self.start_time

        if elapsed <= 0:
            return

        hz = self.frame_count / elapsed

        if self.last_time is None:
            self.get_logger().warn(
                'No depth frames received'
            )
            return

        age = time.time() - self.last_time

        if age > 2.0:
            self.get_logger().warn(
                f'Depth stream stopped. '
                f'Last frame {age:.1f}s ago'
            )
        else:
            self.get_logger().info(
                f'Depth stream OK | '
                f'frames={self.frame_count} | '
                f'avg={hz:.1f} Hz'
            )


def main(args=None):

    rclpy.init(args=args)

    node = DepthMonitor()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass

    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
