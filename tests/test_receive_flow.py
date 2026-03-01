from openspace_egse.ccsds import (
    SpacePacket,
    SdlpSpacePacketReceiver,
    SdlpUartStreamSerializer,
    TcTransferFrame,
    TmTransferFrame,
    receive_and_print_once,
)


class FakeSerialPort:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)

    @property
    def in_waiting(self) -> int:
        if not self._chunks:
            return 0
        return len(self._chunks[0])

    def read(self, size: int = 1) -> bytes:
        if not self._chunks:
            return b""
        head = self._chunks[0]
        if size >= len(head):
            self._chunks.pop(0)
            return head
        out = head[:size]
        self._chunks[0] = head[size:]
        return out


def test_receive_flow_tm_reverse_path() -> None:
    source_packet = SpacePacket.build_tm(
        apid=45,
        sequence_count=7,
        payload=b"\xDE\xAD\xBE\xEF",
    )
    tm_frame = TmTransferFrame.build(
        spacecraft_id=1,
        virtual_channel_id=0,
        master_channel_frame_count=3,
        virtual_channel_frame_count=4,
        payload=source_packet.encode(),
        first_header_pointer=0,
    )
    uart_stream = SdlpUartStreamSerializer.serialize_tm(tm_frame)

    receiver = SdlpSpacePacketReceiver()
    decoded = receiver.process_uart_bytes(uart_stream)

    assert len(decoded) == 1
    assert decoded[0].space_packet == source_packet


def test_receive_flow_tc_reverse_path() -> None:
    source_packet = SpacePacket.build_tc(
        apid=100,
        sequence_count=11,
        payload=b"\x01\x02\x03",
    )
    tc_frame = TcTransferFrame.build(
        spacecraft_id=2,
        virtual_channel_id=5,
        frame_sequence_number=9,
        payload=source_packet.encode(),
    )
    uart_stream = SdlpUartStreamSerializer.serialize_tc(tc_frame)

    receiver = SdlpSpacePacketReceiver()
    decoded = receiver.process_uart_bytes(uart_stream)

    assert len(decoded) == 1
    assert decoded[0].space_packet == source_packet


def test_receive_and_print_once_prints_packet_line(capsys) -> None:
    source_packet = SpacePacket.build_tm(
        apid=5,
        sequence_count=1,
        payload=b"\xAA\xBB",
    )
    tm_frame = TmTransferFrame.build(
        spacecraft_id=1,
        virtual_channel_id=1,
        master_channel_frame_count=1,
        virtual_channel_frame_count=2,
        payload=source_packet.encode(),
        first_header_pointer=0,
    )
    uart_stream = SdlpUartStreamSerializer.serialize_tm(tm_frame)

    fake_serial = FakeSerialPort([uart_stream])
    decoded = receive_and_print_once(fake_serial)

    assert len(decoded) == 1
    stdout = capsys.readouterr().out
    assert "[TM]" in stdout
    assert "APID=5" in stdout
    assert "DATA_HEX=AABB" in stdout


def test_receiver_handles_fragmented_uart_input() -> None:
    source_packet = SpacePacket.build_tc(
        apid=12,
        sequence_count=33,
        payload=b"\x10\x20\x30\x40",
    )
    tc_frame = TcTransferFrame.build(
        spacecraft_id=3,
        virtual_channel_id=2,
        frame_sequence_number=7,
        payload=source_packet.encode(),
        fecf=b"\x00\x00",
    )
    uart_stream = SdlpUartStreamSerializer.serialize_tc(tc_frame)

    receiver = SdlpSpacePacketReceiver()
    split = len(uart_stream) // 2
    assert receiver.process_uart_bytes(uart_stream[:split]) == []
    decoded = receiver.process_uart_bytes(uart_stream[split:])

    assert len(decoded) == 1
    assert decoded[0].space_packet == source_packet
