"""Jetson bridge entry point; imports ROS only after argument parsing."""
from ai_rescue_uwb_common.ros_adapter import main_for_role

def main(args=None) -> int:
    return main_for_role("jetson", args)

if __name__ == "__main__":
    raise SystemExit(main())
