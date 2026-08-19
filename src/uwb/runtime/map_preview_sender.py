from __future__ import annotations
from pathlib import Path
from typing import Any, Mapping
from .ports import ArtifactSenderPort

class MapPreviewSender:
    def __init__(self, sender: ArtifactSenderPort) -> None:
        self._sender = sender
    def send(self, path: Path, *, mission_id: str, artifact_version: int) -> Mapping[str, Any]:
        return self._sender.send_artifact(path, artifact_type="map_preview", mission_id=mission_id, artifact_version=artifact_version, priority=80)
