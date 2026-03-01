from openspace_egse.ccsds import (
    SdlpFrameType,
    SdlpUartStreamParser,
    SdlpUartStreamSerializer,
    TcTransferFrame,
    TmTransferFrame,
)


def test_uart_stream_tm_roundtrip_with_chunked_input_and_escaping() -> None:
    tm = TmTransferFrame.build(
        spacecraft_id=12,
        virtual_channel_id=2,
        master_channel_frame_count=1,
        virtual_channel_frame_count=2,
        payload=b"\xC0\xDB\x10\x20",
        first_header_pointer=0,
    )
    encoded_stream = SdlpUartStreamSerializer.serialize_tm(tm)

    parser = SdlpUartStreamParser()
    part_a = encoded_stream[:3]
    part_b = encoded_stream[3:8]
    part_c = encoded_stream[8:]

    assert parser.feed(part_a) == []
    assert parser.feed(part_b) == []
    parsed = parser.feed(part_c)

    assert len(parsed) == 1
    assert parsed[0].frame_type == SdlpFrameType.TM
    assert parsed[0].frame == tm
    assert parsed[0].has_fecf is False


def test_uart_stream_parses_multiple_frames_in_single_feed() -> None:
    tm = TmTransferFrame.build(
        spacecraft_id=1,
        virtual_channel_id=0,
        master_channel_frame_count=10,
        virtual_channel_frame_count=11,
        payload=b"\x01\x02",
        first_header_pointer=0,
    )
    tc = TcTransferFrame.build(
        spacecraft_id=2,
        virtual_channel_id=3,
        frame_sequence_number=99,
        payload=b"\xAA\xBB\xCC",
        fecf=b"\x00\x00",
    )

    stream = (
        SdlpUartStreamSerializer.serialize_tm(tm)
        + SdlpUartStreamSerializer.serialize_tc(tc)
    )

    parser = SdlpUartStreamParser()
    parsed = parser.feed(stream)

    assert len(parsed) == 2
    assert parsed[0].frame_type == SdlpFrameType.TM
    assert parsed[0].frame == tm
    assert parsed[1].frame_type == SdlpFrameType.TC
    assert parsed[1].frame == tc
    assert parsed[1].has_fecf is True


def test_uart_stream_ignores_frame_with_invalid_length() -> None:
    tm = TmTransferFrame.build(
        spacecraft_id=9,
        virtual_channel_id=1,
        master_channel_frame_count=3,
        virtual_channel_frame_count=4,
        payload=b"\x11\x22\x33",
        first_header_pointer=0,
    )
    valid_stream = SdlpUartStreamSerializer.serialize_tm(tm)

    corrupted = bytearray(valid_stream)
    first_payload_index = 1
    length_msb_index = first_payload_index + 2
    corrupted[length_msb_index] ^= 0x01

    parser = SdlpUartStreamParser()
    assert parser.feed(bytes(corrupted)) == []


def test_uart_stream_tc_roundtrip_with_fecf() -> None:
    tc = TcTransferFrame.build(
        spacecraft_id=99,
        virtual_channel_id=12,
        frame_sequence_number=7,
        payload=b"\x10\x20\x30\x40",
        bypass_flag=True,
        control_command_flag=True,
        fecf=b"\xCA\xFE",
    )

    stream = SdlpUartStreamSerializer.serialize_tc(tc)
    parser = SdlpUartStreamParser()
    parsed = parser.feed(stream)

    assert len(parsed) == 1
    assert parsed[0].frame_type == SdlpFrameType.TC
    assert parsed[0].frame == tc
    assert parsed[0].has_fecf is True
