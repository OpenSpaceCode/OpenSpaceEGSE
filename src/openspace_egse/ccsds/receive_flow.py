from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from openspace_egse.config import EGSE_SERIAL_MAX_READ_SIZE

from .sdlp import TcTransferFrame, TmTransferFrame
from .sdlp_uart import ParsedSdlpFrame, SdlpFrameType, SdlpUartStreamParser
from .space_packet import SpacePacket


SPACE_PACKET_PRIMARY_HEADER_LENGTH = 6
SPACE_PACKET_DATA_LENGTH_FIELD_START = 4
SPACE_PACKET_DATA_LENGTH_FIELD_END = 6


class SerialLike(Protocol):
    @property
    def in_waiting(self) -> int:
        ...

    def read(self, size: int = 1) -> bytes:
        ...


@dataclass(slots=True, frozen=True)
class DecodedSpacePacket:
    frame_type: SdlpFrameType
    space_packet: SpacePacket


class SdlpSpacePacketReceiver:
    def __init__(self) -> None:
        self._uart_parser = SdlpUartStreamParser()

    def process_uart_bytes(self, uart_chunk: bytes) -> list[DecodedSpacePacket]:
        parsed_frames = self._uart_parser.feed(uart_chunk)
        decoded_packets: list[DecodedSpacePacket] = []
        for parsed_frame in parsed_frames:
            decoded_packets.extend(self._decode_packets_from_sdlp_frame(parsed_frame))
        return decoded_packets

    def process_serial_once(
        self,
        serial_port: SerialLike,
        *,
        max_read_size: int = EGSE_SERIAL_MAX_READ_SIZE,
    ) -> list[DecodedSpacePacket]:
        if max_read_size <= 0:
            raise ValueError("max_read_size must be positive")

        pending = int(serial_port.in_waiting)
        if pending <= 0:
            return []

        to_read = pending if pending < max_read_size else max_read_size
        chunk = serial_port.read(to_read)
        if not chunk:
            return []
        return self.process_uart_bytes(chunk)

    def process_serial_forever(
        self,
        serial_port: SerialLike,
        *,
        max_read_size: int = EGSE_SERIAL_MAX_READ_SIZE,
    ) -> None:
        while True:
            decoded_packets = self.process_serial_once(
                serial_port,
                max_read_size=max_read_size,
            )
            for item in decoded_packets:
                print(format_space_packet(item))

    def _decode_packets_from_sdlp_frame(
        self,
        parsed_frame: ParsedSdlpFrame,
    ) -> list[DecodedSpacePacket]:
        if parsed_frame.frame_type == SdlpFrameType.TM:
            tm_frame = parsed_frame.frame
            if not isinstance(tm_frame, TmTransferFrame):
                return []
            start_offset = _tm_start_offset(tm_frame)
            return _decode_space_packets_from_payload(
                frame_type=SdlpFrameType.TM,
                payload=tm_frame.data_field,
                start_offset=start_offset,
            )

        tc_frame = parsed_frame.frame
        if not isinstance(tc_frame, TcTransferFrame):
            return []
        return _decode_space_packets_from_payload(
            frame_type=SdlpFrameType.TC,
            payload=tc_frame.data_field,
            start_offset=0,
        )


def _tm_start_offset(tm_frame: TmTransferFrame) -> int:
    if tm_frame.first_header_pointer == 0x07FF:
        return len(tm_frame.data_field)
    if tm_frame.first_header_pointer > len(tm_frame.data_field):
        return len(tm_frame.data_field)
    return tm_frame.first_header_pointer


def _decode_space_packets_from_payload(
    *,
    frame_type: SdlpFrameType,
    payload: bytes,
    start_offset: int,
) -> list[DecodedSpacePacket]:
    decoded: list[DecodedSpacePacket] = []
    offset = start_offset

    while offset + SPACE_PACKET_PRIMARY_HEADER_LENGTH <= len(payload):
        packet_data_length = int.from_bytes(
            payload[
                offset
                + SPACE_PACKET_DATA_LENGTH_FIELD_START : offset
                + SPACE_PACKET_DATA_LENGTH_FIELD_END
            ],
            "big",
        )
        packet_total_length = SPACE_PACKET_PRIMARY_HEADER_LENGTH + packet_data_length + 1
        packet_end = offset + packet_total_length
        if packet_end > len(payload):
            break

        raw_packet = bytes(payload[offset:packet_end])
        try:
            packet = SpacePacket.decode(raw_packet)
        except (TypeError, ValueError):
            break

        decoded.append(DecodedSpacePacket(frame_type=frame_type, space_packet=packet))
        offset = packet_end

    return decoded


def format_space_packet(decoded_packet: DecodedSpacePacket) -> str:
    packet = decoded_packet.space_packet
    return (
        f"[{decoded_packet.frame_type.name}] "
        f"APID={packet.apid} "
        f"TYPE={packet.packet_type.name} "
        f"SEQ={packet.sequence_count} "
        f"LEN={len(packet.data_field)} "
        f"DATA_HEX={packet.data_field.hex().upper()}"
    )


def receive_and_print_once(
    serial_port: SerialLike,
    receiver: SdlpSpacePacketReceiver | None = None,
    *,
    max_read_size: int = EGSE_SERIAL_MAX_READ_SIZE,
) -> list[DecodedSpacePacket]:
    active_receiver = receiver if receiver is not None else SdlpSpacePacketReceiver()
    decoded = active_receiver.process_serial_once(
        serial_port,
        max_read_size=max_read_size,
    )
    for item in decoded:
        print(format_space_packet(item))
    return decoded
