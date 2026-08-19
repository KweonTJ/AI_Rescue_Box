from pathlib import Path
from ai_rescue_uwb_common import ArtifactMetadata, DataPacket, decode_packet, encode_packet, create_memory_link

def test_data_packet_roundtrip():
    packet=DataPacket('1234abcd',3,b'abc'); assert decode_packet(encode_packet(packet))==packet
def test_metadata_contract(tmp_path: Path):
    path=tmp_path/'mission.json'; path.write_bytes(b'{}')
    meta=ArtifactMetadata.from_file(path,artifact_type='mission_manifest',mission_id='m1',artifact_version=1,sender='host')
    assert meta.file_size==2 and len(meta.sha256)==64
def test_memory_link_ack():
    first,second=create_memory_link(); receipt=first.send_line(b'hello'); assert receipt.acknowledged and second.receive_line(0.1)==b'hello'
