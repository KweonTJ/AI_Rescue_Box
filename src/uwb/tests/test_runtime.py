from pathlib import Path

from runtime.coordinator import MissionArtifactCoordinator
from runtime.mission_artifacts import ReceivedMissionArtifact


def artifact(kind: str, sha: str) -> ReceivedMissionArtifact:
    return ReceivedMissionArtifact(
        transfer_id=f"{kind}-tx",
        artifact_type=kind,
        mission_id="m1",
        artifact_version=2,
        local_file_path=Path(f"/{kind}"),
        sha256=sha,
    )


def test_mission_pair_is_emitted_only_after_both_artifacts():
    coordinator = MissionArtifactCoordinator()
    assert coordinator.observe(artifact("mission_manifest", "a" * 64)) is None
    pair = coordinator.observe(artifact("base_map", "b" * 64))
    assert pair is not None
    assert pair.mission_id == "m1"
    assert pair.artifact_version == 2
