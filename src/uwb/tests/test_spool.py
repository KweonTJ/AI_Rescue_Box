from pathlib import Path

from ai_rescue_uwb_common import (
    ArtifactMetadata,
    DataPacket,
    MetaPacket,
    SpoolManager,
    StartPacket,
    packetize_file,
)


def test_packetized_artifact_reassembles_through_spool(tmp_path: Path) -> None:
    source = tmp_path / "semantic_result.json"
    content = b'{"mission_id":"m1","result_version":1}' * 8
    source.write_bytes(content)
    metadata = ArtifactMetadata.from_file(
        source,
        artifact_type="semantic_result",
        mission_id="m1",
        artifact_version=1,
        sender="jetson",
    )

    manager = SpoolManager(tmp_path / "spool")
    staged = manager.stage_outgoing(source, metadata)
    assert staged.read_bytes() == content

    packets = list(packetize_file(staged, metadata, "1234abcd"))
    start = packets[0]
    assert isinstance(start, StartPacket)

    incoming = manager.begin_incoming(
        start.transfer_id,
        start.metadata_chunks,
        start.data_chunks,
    )
    metadata_packets = [item for item in packets if isinstance(item, MetaPacket)]
    data_packets = [item for item in packets if isinstance(item, DataPacket)]

    for packet in metadata_packets:
        incoming.accept_metadata_chunk(packet.index, packet.data)
    for packet in reversed(data_packets):
        incoming.accept_data_chunk(packet.index, packet.data)

    completed = incoming.complete()
    assert completed.path.read_bytes() == content
    assert completed.metadata.sha256 == metadata.sha256
    assert completed.path.is_file()
