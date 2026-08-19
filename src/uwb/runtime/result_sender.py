from __future__ import annotations
from pathlib import Path
from typing import Any, Mapping
from .ports import ArtifactSenderPort

class SemanticResultSender:
    def __init__(self, sender: ArtifactSenderPort) -> None:
        self._sender = sender
    def send(self, path: Path, *, mission_id: str, result_version: int) -> Mapping[str, Any]:
        return self._sender.send_artifact(path, artifact_type="semantic_result", mission_id=mission_id, artifact_version=result_version, priority=220)
