from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


PRIMARY_HEADER_LENGTH = 6
MAX_APID = 0x07FF
MAX_SEQUENCE_COUNT = 0x3FFF
MAX_DATA_LENGTH_FIELD = 0xFFFF


class PacketType(IntEnum):
    TELEMETRY = 0
    TELECOMMAND = 1


class SequenceFlags(IntEnum):
    CONTINUATION_SEGMENT = 0
    FIRST_SEGMENT = 1
    LAST_SEGMENT = 2
    UNSEGMENTED = 3


@dataclass(slots=True, frozen=True)
class SpacePacket:
    apid: int
    packet_type: PacketType
    sequence_flags: SequenceFlags
    sequence_count: int
    data_field: bytes
    secondary_header_flag: bool = False
    version: int = 0

    def __post_init__(self) -> None:
        if not 0 <= self.version <= 0x07:
            raise ValueError("version must be in range 0..7")
        if not 0 <= self.apid <= MAX_APID:
            raise ValueError(f"apid must be in range 0..{MAX_APID}")
        if not 0 <= self.sequence_count <= MAX_SEQUENCE_COUNT:
            raise ValueError(f"sequence_count must be in range 0..{MAX_SEQUENCE_COUNT}")
        if not isinstance(self.data_field, (bytes, bytearray)):
            raise TypeError("data_field must be bytes-like")
        if len(self.data_field) == 0:
            raise ValueError("data_field must not be empty")
        if len(self.data_field) - 1 > MAX_DATA_LENGTH_FIELD:
            raise ValueError("data_field is too large for CCSDS packet length field")

    @property
    def data_length(self) -> int:
        return len(self.data_field) - 1

    @property
    def total_length(self) -> int:
        return PRIMARY_HEADER_LENGTH + len(self.data_field)

    def encode(self) -> bytes:
        first_word = (
            ((self.version & 0x07) << 13)
            | ((int(self.packet_type) & 0x01) << 12)
            | ((1 if self.secondary_header_flag else 0) << 11)
            | (self.apid & MAX_APID)
        )
        second_word = ((int(self.sequence_flags) & 0x03) << 14) | (
            self.sequence_count & MAX_SEQUENCE_COUNT
        )
        header = (
            first_word.to_bytes(2, byteorder="big")
            + second_word.to_bytes(2, byteorder="big")
            + self.data_length.to_bytes(2, byteorder="big")
        )
        return header + bytes(self.data_field)

    @classmethod
    def decode(cls, raw_packet: bytes) -> SpacePacket:
        if not isinstance(raw_packet, (bytes, bytearray)):
            raise TypeError("raw_packet must be bytes-like")
        if len(raw_packet) < PRIMARY_HEADER_LENGTH + 1:
            raise ValueError("raw_packet is too short to contain a valid CCSDS packet")

        first_word = int.from_bytes(raw_packet[0:2], byteorder="big")
        second_word = int.from_bytes(raw_packet[2:4], byteorder="big")
        data_length = int.from_bytes(raw_packet[4:6], byteorder="big")

        expected_data_field_len = data_length + 1
        expected_total_len = PRIMARY_HEADER_LENGTH + expected_data_field_len
        if len(raw_packet) != expected_total_len:
            raise ValueError(
                "raw_packet length does not match CCSDS packet length field"
            )

        version = (first_word >> 13) & 0x07
        packet_type = PacketType((first_word >> 12) & 0x01)
        secondary_header_flag = bool((first_word >> 11) & 0x01)
        apid = first_word & MAX_APID

        sequence_flags = SequenceFlags((second_word >> 14) & 0x03)
        sequence_count = second_word & MAX_SEQUENCE_COUNT

        data_field = bytes(raw_packet[6:])

        return cls(
            version=version,
            packet_type=packet_type,
            secondary_header_flag=secondary_header_flag,
            apid=apid,
            sequence_flags=sequence_flags,
            sequence_count=sequence_count,
            data_field=data_field,
        )

    @classmethod
    def build_tm(
        cls,
        apid: int,
        sequence_count: int,
        payload: bytes,
        *,
        secondary_header_flag: bool = False,
        sequence_flags: SequenceFlags = SequenceFlags.UNSEGMENTED,
    ) -> SpacePacket:
        return cls(
            apid=apid,
            packet_type=PacketType.TELEMETRY,
            secondary_header_flag=secondary_header_flag,
            sequence_flags=sequence_flags,
            sequence_count=sequence_count,
            data_field=payload,
        )

    @classmethod
    def build_tc(
        cls,
        apid: int,
        sequence_count: int,
        payload: bytes,
        *,
        secondary_header_flag: bool = False,
        sequence_flags: SequenceFlags = SequenceFlags.UNSEGMENTED,
    ) -> SpacePacket:
        return cls(
            apid=apid,
            packet_type=PacketType.TELECOMMAND,
            secondary_header_flag=secondary_header_flag,
            sequence_flags=sequence_flags,
            sequence_count=sequence_count,
            data_field=payload,
        )
