import pytest

from openspace_egse.ccsds import (
    TcCommandName,
    TcCommandSender,
    TcSendConfig,
    available_tc_commands,
    build_tc_command_payload,
    SdlpSpacePacketReceiver,
)


class FakeSerialWriter:
    def __init__(self, *, partial_write: bool = False) -> None:
        self.partial_write = partial_write
        self.writes: list[bytes] = []

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        if self.partial_write:
            return len(data) - 1
        return len(data)


def test_available_tc_commands() -> None:
    assert available_tc_commands() == ("ping", "set_mode", "reset_subsystem")


def test_build_tc_command_payloads() -> None:
    assert build_tc_command_payload(TcCommandName.PING, 258) == b"\x01\x01\x02"
    assert build_tc_command_payload("set_mode", 3) == b"\x02\x03"
    assert build_tc_command_payload("reset_subsystem", 4) == b"\x03\x04"


def test_build_payload_rejects_invalid_parameter_ranges() -> None:
    with pytest.raises(ValueError, match="0..255"):
        build_tc_command_payload("set_mode", 256)

    with pytest.raises(ValueError, match="0..65535"):
        build_tc_command_payload("ping", 70000)


def test_sender_send_builds_uart_stream_and_is_decodable() -> None:
    serial = FakeSerialWriter()
    sender = TcCommandSender(
        serial_port=serial,
        config=TcSendConfig(
            spacecraft_id=5,
            virtual_channel_id=1,
            space_packet_apid=120,
        ),
        initial_packet_sequence_count=10,
        initial_frame_sequence_number=20,
    )

    sent = sender.send(TcCommandName.PING, 513)

    assert len(serial.writes) == 1
    assert sent.bytes_written == len(serial.writes[0])
    assert sent.command_payload == b"\x01\x02\x01"
    assert sender.packet_sequence_count == 11
    assert sender.frame_sequence_number == 21

    receiver = SdlpSpacePacketReceiver()
    decoded = receiver.process_uart_bytes(serial.writes[0])
    assert len(decoded) == 1
    assert decoded[0].space_packet == sent.space_packet
    assert decoded[0].space_packet.data_field == b"\x01\x02\x01"


def test_sender_rejects_partial_serial_write() -> None:
    serial = FakeSerialWriter(partial_write=True)
    sender = TcCommandSender(
        serial_port=serial,
        config=TcSendConfig(
            spacecraft_id=5,
            virtual_channel_id=1,
            space_packet_apid=120,
        ),
    )

    with pytest.raises(OSError, match="incomplete"):
        sender.send("set_mode", 2)
