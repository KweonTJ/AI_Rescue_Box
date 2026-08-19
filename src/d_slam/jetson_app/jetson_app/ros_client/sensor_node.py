from __future__ import annotations
from .adapters import SensorPorts

class SensorNode:
    """Stage 1 ownership boundary for Astra/TF/SLAM adapters.

    ROS subscriptions are intentionally not mission-wired here; existing sensor
    and SLAM packages under src/d_slam own the hardware graph.
    """
    def __init__(self, ports: SensorPorts) -> None: self.ports=ports
    def status(self) -> dict[str,object]:
        slam=self.ports.slam.status()
        return {"slam":{"connected":slam.connected,"mode":slam.mode.value,"message":slam.message},"detector":self.ports.detector is not None,"depth":self.ports.depth is not None,"tf":self.ports.tf is not None}
