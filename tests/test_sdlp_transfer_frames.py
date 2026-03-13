import pytest

from openspace_egse.ccsds import TcTransferFrame, TmTransferFrame


def test_tm_transfer_frame_roundtrip_with_ocf_and_fecf() -> None:
    frame = TmTransferFrame.build(
        spacecraft_id=21,
        virtual_channel_id=3,
        master_channel_frame_count=10,
        virtual_channel_frame_count=11,
        payload=b"\x01\x02\x03\x04",
        first_header_pointer=0,
        secondary_header_flag=False,
        synch_flag=False,
        packet_order_flag=False,
        segment_length_id=0b11,
        ocf=b"\xaa\xbb\xcc\xdd",
        fecf=b"\xee\xff",
    )

    raw = frame.encode()
    decoded = TmTransferFrame.decode(raw, has_fecf=True)

    assert decoded == frame
    assert decoded.total_length == len(raw)


def test_tm_transfer_frame_roundtrip_without_trailer() -> None:
    frame = TmTransferFrame.build(
        spacecraft_id=2,
        virtual_channel_id=1,
        master_channel_frame_count=200,
        virtual_channel_frame_count=201,
        payload=b"\x10\x20",
        first_header_pointer=0x07FF,
    )

    raw = frame.encode()
    decoded = TmTransferFrame.decode(raw)

    assert decoded == frame
    assert decoded.ocf is None
    assert decoded.fecf is None


def test_tc_transfer_frame_roundtrip_with_fecf() -> None:
    frame = TcTransferFrame.build(
        spacecraft_id=100,
        virtual_channel_id=7,
        frame_sequence_number=33,
        payload=b"\x99\x88\x77",
        bypass_flag=True,
        control_command_flag=False,
        fecf=b"\x12\x34",
    )

    raw = frame.encode()
    decoded = TcTransferFrame.decode(raw, has_fecf=True)

    assert decoded == frame
    assert decoded.frame_length_field == len(raw) - 1


def test_tc_decode_raises_on_length_mismatch() -> None:
    frame = TcTransferFrame.build(
        spacecraft_id=55,
        virtual_channel_id=4,
        frame_sequence_number=1,
        payload=b"\x01\x02",
    )
    raw = frame.encode()
    truncated = raw[:-1]

    with pytest.raises(ValueError, match="length"):
        TcTransferFrame.decode(truncated)


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "spacecraft_id": 0x0400,
            "virtual_channel_id": 0,
            "master_channel_frame_count": 0,
            "virtual_channel_frame_count": 0,
            "first_header_pointer": 0,
            "data_field": b"\x00",
        },
        {
            "spacecraft_id": 1,
            "virtual_channel_id": 8,
            "master_channel_frame_count": 0,
            "virtual_channel_frame_count": 0,
            "first_header_pointer": 0,
            "data_field": b"\x00",
        },
        {
            "spacecraft_id": 1,
            "virtual_channel_id": 0,
            "master_channel_frame_count": 0,
            "virtual_channel_frame_count": 0,
            "first_header_pointer": 0,
            "data_field": b"\x00",
            "ocf_flag": True,
            "ocf": b"\xaa",
        },
    ],
)
def test_tm_validation_errors(kwargs) -> None:
    with pytest.raises(ValueError):
        TmTransferFrame(**kwargs)
