"""Generate Stage 2 mock artifacts and submit them through the public UWB action."""
from __future__ import annotations

import argparse
import os
import threading
from pathlib import Path
from typing import Any

from .mission import MissionManager
from .stage2_mock import Stage2MockGenerator


def _wait(future: Any, timeout: float) -> Any:
    event = threading.Event(); box: dict[str, Any] = {}
    def done(completed: Any) -> None:
        try: box['result'] = completed.result()
        except Exception as error: box['error'] = error
        event.set()
    future.add_done_callback(done)
    if not event.wait(timeout): raise TimeoutError('ROS action timed out')
    if 'error' in box: raise box['error']
    return box.get('result')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Generate and submit Stage 2 mock rescue artifacts')
    parser.add_argument('--no-submit', action='store_true', help='generate files only')
    args = parser.parse_args(argv)
    root = Path(os.environ.get('AI_RESCUE_DATA_ROOT', 'data')) / 'missions'
    artifacts = Stage2MockGenerator(MissionManager(root)).generate()
    print(f"semantic_result={artifacts.semantic_result_path}")
    print(f"map_preview={artifacts.map_preview_path}")
    if args.no_submit:
        return 0
    try:
        import rclpy
        from ai_rescue_interfaces.action import SubmitRescueUpdate
        from rclpy.action import ActionClient
        from rclpy.executors import MultiThreadedExecutor
        from rclpy.node import Node
    except ImportError as error:
        raise RuntimeError('ROS 2 or generated ai_rescue_interfaces are unavailable') from error
    rclpy.init()
    node = Node('ai_rescue_stage2_mock_submitter')
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)
    thread = threading.Thread(target=executor.spin, daemon=True)
    thread.start()
    try:
        client = ActionClient(node, SubmitRescueUpdate, '/uwb/submit_rescue_update')
        if not client.wait_for_server(timeout_sec=5.0):
            raise RuntimeError('/uwb/submit_rescue_update is unavailable')
        goal = SubmitRescueUpdate.Goal()
        goal.mission_id = artifacts.mission_id
        goal.mission_version = artifacts.mission_version
        goal.result_version = artifacts.result_version
        goal.semantic_result_path = str(artifacts.semantic_result_path.resolve())
        handle = _wait(client.send_goal_async(goal), 5.0)
        if not handle.accepted:
            raise RuntimeError('SubmitRescueUpdate goal was rejected')
        response = _wait(handle.get_result_async(), 60.0).result
        if not response.accepted:
            raise RuntimeError(response.message)
        print(f"transfer_id={response.transfer_id}")
        return 0
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    raise SystemExit(main())
