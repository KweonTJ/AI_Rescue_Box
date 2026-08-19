from __future__ import annotations
from pathlib import Path
from typing import Mapping, Any, Protocol

class ArtifactSenderPort(Protocol):
    def send_artifact(self, path: Path, *, artifact_type: str, mission_id: str, artifact_version: int, priority: int = 100) -> Mapping[str, Any]: ...

class ArtifactAcknowledgerPort(Protocol):
    def acknowledge(self, transfer_id: str, *, applied: bool, error_message: str = "") -> None: ...
