import pytest

from openspace_egse.ccsds import PacketType, SequenceFlags, SpacePacket


def test_encode_decode_roundtrip_tm_packet() -> None:
    packet = SpacePacket.build_tm(
        apid=123,
        sequence_count=42,
        payload=b"\x10\x20\x30",
        secondary_header_flag=True,
        sequence_flags=SequenceFlags.UNSEGMENTED,
    )

    raw = packet.encode()
    decoded = SpacePacket.decode(raw)

    assert decoded == packet
    assert decoded.packet_type == PacketType.TELEMETRY
    assert decoded.data_length == 2
    assert decoded.total_length == 9


def test_encode_decode_roundtrip_tc_packet() -> None:
    packet = SpacePacket.build_tc(
        apid=1,
        sequence_count=0,
        payload=b"\x01",
        sequence_flags=SequenceFlags.FIRST_SEGMENT,
    )

    raw = packet.encode()
    decoded = SpacePacket.decode(raw)

    assert decoded.packet_type == PacketType.TELECOMMAND
    assert decoded.apid == 1
    assert decoded.sequence_flags == SequenceFlags.FIRST_SEGMENT
    assert decoded.sequence_count == 0
    assert decoded.data_field == b"\x01"


def test_decode_raises_on_mismatched_length() -> None:
    packet = SpacePacket.build_tm(apid=5, sequence_count=9, payload=b"\xAA\xBB")
    raw = packet.encode()
    invalid = raw[:-1]

    with pytest.raises(ValueError, match="length"):
        SpacePacket.decode(invalid)


@pytest.mark.parametrize(
    "kwargs,error_type",
    [
        (
            {
                "apid": 0x0800,
                "packet_type": PacketType.TELEMETRY,
                "sequence_flags": SequenceFlags.UNSEGMENTED,
                "sequence_count": 0,
                "data_field": b"\x00",
            },
            ValueError,
        ),
        (
            {
                "apid": 1,
                "packet_type": PacketType.TELEMETRY,
                "sequence_flags": SequenceFlags.UNSEGMENTED,
                "sequence_count": 0x4000,
                "data_field": b"\x00",
            },
            ValueError,
        ),
        (
            {
                "apid": 1,
                "packet_type": PacketType.TELEMETRY,
                "sequence_flags": SequenceFlags.UNSEGMENTED,
                "sequence_count": 1,
                "data_field": b"",
            },
            ValueError,
        ),
    ],
)
def test_invalid_field_ranges(kwargs, error_type) -> None:
    with pytest.raises(error_type):
        SpacePacket(**kwargs)
