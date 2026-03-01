from __future__ import annotations

from dataclasses import dataclass


TM_PRIMARY_HEADER_LENGTH = 6
TC_PRIMARY_HEADER_LENGTH = 5
TM_OCF_LENGTH = 4
FECF_LENGTH = 2


@dataclass(slots=True, frozen=True)
class TmTransferFrame:
    spacecraft_id: int
    virtual_channel_id: int
    master_channel_frame_count: int
    virtual_channel_frame_count: int
    first_header_pointer: int
    data_field: bytes
    ocf_flag: bool = False
    secondary_header_flag: bool = False
    synch_flag: bool = False
    packet_order_flag: bool = False
    segment_length_id: int = 0b11
    version: int = 0
    ocf: bytes | None = None
    fecf: bytes | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.version <= 0x03:
            raise ValueError("version must be in range 0..3")
        if not 0 <= self.spacecraft_id <= 0x03FF:
            raise ValueError("spacecraft_id must be in range 0..1023")
        if not 0 <= self.virtual_channel_id <= 0x07:
            raise ValueError("virtual_channel_id must be in range 0..7")
        if not 0 <= self.master_channel_frame_count <= 0xFF:
            raise ValueError("master_channel_frame_count must be in range 0..255")
        if not 0 <= self.virtual_channel_frame_count <= 0xFF:
            raise ValueError("virtual_channel_frame_count must be in range 0..255")
        if not 0 <= self.first_header_pointer <= 0x07FF:
            raise ValueError("first_header_pointer must be in range 0..2047")
        if not 0 <= self.segment_length_id <= 0x03:
            raise ValueError("segment_length_id must be in range 0..3")
        if not isinstance(self.data_field, (bytes, bytearray)):
            raise TypeError("data_field must be bytes-like")
        if self.ocf_flag:
            if self.ocf is None:
                raise ValueError("ocf must be provided when ocf_flag is set")
            if len(self.ocf) != TM_OCF_LENGTH:
                raise ValueError("ocf must be exactly 4 bytes")
        elif self.ocf is not None:
            raise ValueError("ocf must be None when ocf_flag is not set")
        if self.fecf is not None and len(self.fecf) != FECF_LENGTH:
            raise ValueError("fecf must be exactly 2 bytes")

    @property
    def total_length(self) -> int:
        ocf_len = TM_OCF_LENGTH if self.ocf_flag else 0
        fecf_len = FECF_LENGTH if self.fecf is not None else 0
        return TM_PRIMARY_HEADER_LENGTH + len(self.data_field) + ocf_len + fecf_len

    def encode(self) -> bytes:
        first_word = (
            ((self.version & 0x03) << 14)
            | ((self.spacecraft_id & 0x03FF) << 4)
            | ((self.virtual_channel_id & 0x07) << 1)
            | (1 if self.ocf_flag else 0)
        )
        second_word = (
            ((1 if self.secondary_header_flag else 0) << 15)
            | ((1 if self.synch_flag else 0) << 14)
            | ((1 if self.packet_order_flag else 0) << 13)
            | ((self.segment_length_id & 0x03) << 11)
            | (self.first_header_pointer & 0x07FF)
        )
        frame = bytearray()
        frame += first_word.to_bytes(2, "big")
        frame += self.master_channel_frame_count.to_bytes(1, "big")
        frame += self.virtual_channel_frame_count.to_bytes(1, "big")
        frame += second_word.to_bytes(2, "big")
        frame += bytes(self.data_field)
        if self.ocf_flag and self.ocf is not None:
            frame += self.ocf
        if self.fecf is not None:
            frame += self.fecf
        return bytes(frame)

    @classmethod
    def decode(cls, raw_frame: bytes, *, has_fecf: bool = False) -> TmTransferFrame:
        if not isinstance(raw_frame, (bytes, bytearray)):
            raise TypeError("raw_frame must be bytes-like")
        if len(raw_frame) < TM_PRIMARY_HEADER_LENGTH:
            raise ValueError("raw_frame is too short for TM transfer frame")

        first_word = int.from_bytes(raw_frame[0:2], "big")
        version = (first_word >> 14) & 0x03
        spacecraft_id = (first_word >> 4) & 0x03FF
        virtual_channel_id = (first_word >> 1) & 0x07
        ocf_flag = bool(first_word & 0x01)

        mcfc = raw_frame[2]
        vcfc = raw_frame[3]

        second_word = int.from_bytes(raw_frame[4:6], "big")
        secondary_header_flag = bool((second_word >> 15) & 0x01)
        synch_flag = bool((second_word >> 14) & 0x01)
        packet_order_flag = bool((second_word >> 13) & 0x01)
        segment_length_id = (second_word >> 11) & 0x03
        first_header_pointer = second_word & 0x07FF

        trailer_len = (TM_OCF_LENGTH if ocf_flag else 0) + (FECF_LENGTH if has_fecf else 0)
        if len(raw_frame) < TM_PRIMARY_HEADER_LENGTH + trailer_len:
            raise ValueError("raw_frame is shorter than TM header plus trailer")

        payload_end = len(raw_frame) - trailer_len
        data_field = bytes(raw_frame[TM_PRIMARY_HEADER_LENGTH:payload_end])

        ocf = None
        if ocf_flag:
            ocf_start = payload_end
            ocf = bytes(raw_frame[ocf_start : ocf_start + TM_OCF_LENGTH])

        fecf = None
        if has_fecf:
            fecf = bytes(raw_frame[-FECF_LENGTH:])

        return cls(
            version=version,
            spacecraft_id=spacecraft_id,
            virtual_channel_id=virtual_channel_id,
            ocf_flag=ocf_flag,
            master_channel_frame_count=mcfc,
            virtual_channel_frame_count=vcfc,
            secondary_header_flag=secondary_header_flag,
            synch_flag=synch_flag,
            packet_order_flag=packet_order_flag,
            segment_length_id=segment_length_id,
            first_header_pointer=first_header_pointer,
            data_field=data_field,
            ocf=ocf,
            fecf=fecf,
        )

    @classmethod
    def build(
        cls,
        *,
        spacecraft_id: int,
        virtual_channel_id: int,
        master_channel_frame_count: int,
        virtual_channel_frame_count: int,
        payload: bytes,
        first_header_pointer: int,
        secondary_header_flag: bool = False,
        synch_flag: bool = False,
        packet_order_flag: bool = False,
        segment_length_id: int = 0b11,
        ocf: bytes | None = None,
        fecf: bytes | None = None,
    ) -> TmTransferFrame:
        return cls(
            spacecraft_id=spacecraft_id,
            virtual_channel_id=virtual_channel_id,
            master_channel_frame_count=master_channel_frame_count,
            virtual_channel_frame_count=virtual_channel_frame_count,
            secondary_header_flag=secondary_header_flag,
            synch_flag=synch_flag,
            packet_order_flag=packet_order_flag,
            segment_length_id=segment_length_id,
            first_header_pointer=first_header_pointer,
            data_field=payload,
            ocf_flag=ocf is not None,
            ocf=ocf,
            fecf=fecf,
        )


@dataclass(slots=True, frozen=True)
class TcTransferFrame:
    spacecraft_id: int
    virtual_channel_id: int
    frame_sequence_number: int
    data_field: bytes
    bypass_flag: bool = False
    control_command_flag: bool = False
    version: int = 0
    reserved: int = 0
    fecf: bytes | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.version <= 0x03:
            raise ValueError("version must be in range 0..3")
        if not 0 <= self.reserved <= 0x03:
            raise ValueError("reserved must be in range 0..3")
        if not 0 <= self.spacecraft_id <= 0x03FF:
            raise ValueError("spacecraft_id must be in range 0..1023")
        if not 0 <= self.virtual_channel_id <= 0x3F:
            raise ValueError("virtual_channel_id must be in range 0..63")
        if not 0 <= self.frame_sequence_number <= 0xFF:
            raise ValueError("frame_sequence_number must be in range 0..255")
        if not isinstance(self.data_field, (bytes, bytearray)):
            raise TypeError("data_field must be bytes-like")
        if self.fecf is not None and len(self.fecf) != FECF_LENGTH:
            raise ValueError("fecf must be exactly 2 bytes")

        frame_length = self.total_length - 1
        if frame_length > 0x03FF:
            raise ValueError("TC frame length exceeds 10-bit field")

    @property
    def total_length(self) -> int:
        fecf_len = FECF_LENGTH if self.fecf is not None else 0
        return TC_PRIMARY_HEADER_LENGTH + len(self.data_field) + fecf_len

    @property
    def frame_length_field(self) -> int:
        return self.total_length - 1

    def encode(self) -> bytes:
        first_word = (
            ((self.version & 0x03) << 14)
            | ((1 if self.bypass_flag else 0) << 13)
            | ((1 if self.control_command_flag else 0) << 12)
            | ((self.reserved & 0x03) << 10)
            | (self.spacecraft_id & 0x03FF)
        )
        second_word = (
            ((self.virtual_channel_id & 0x3F) << 10)
            | (self.frame_length_field & 0x03FF)
        )
        frame = bytearray()
        frame += first_word.to_bytes(2, "big")
        frame += second_word.to_bytes(2, "big")
        frame += self.frame_sequence_number.to_bytes(1, "big")
        frame += bytes(self.data_field)
        if self.fecf is not None:
            frame += self.fecf
        return bytes(frame)

    @classmethod
    def decode(cls, raw_frame: bytes, *, has_fecf: bool = False) -> TcTransferFrame:
        if not isinstance(raw_frame, (bytes, bytearray)):
            raise TypeError("raw_frame must be bytes-like")
        if len(raw_frame) < TC_PRIMARY_HEADER_LENGTH:
            raise ValueError("raw_frame is too short for TC transfer frame")

        first_word = int.from_bytes(raw_frame[0:2], "big")
        version = (first_word >> 14) & 0x03
        bypass_flag = bool((first_word >> 13) & 0x01)
        control_command_flag = bool((first_word >> 12) & 0x01)
        reserved = (first_word >> 10) & 0x03
        spacecraft_id = first_word & 0x03FF

        second_word = int.from_bytes(raw_frame[2:4], "big")
        virtual_channel_id = (second_word >> 10) & 0x3F
        frame_length_field = second_word & 0x03FF

        expected_total_len = frame_length_field + 1
        if len(raw_frame) != expected_total_len:
            raise ValueError("raw_frame length does not match TC frame length field")

        frame_sequence_number = raw_frame[4]

        trailer_len = FECF_LENGTH if has_fecf else 0
        if len(raw_frame) < TC_PRIMARY_HEADER_LENGTH + trailer_len:
            raise ValueError("raw_frame is shorter than TC header plus trailer")

        payload_end = len(raw_frame) - trailer_len
        data_field = bytes(raw_frame[TC_PRIMARY_HEADER_LENGTH:payload_end])
        fecf = bytes(raw_frame[-FECF_LENGTH:]) if has_fecf else None

        return cls(
            version=version,
            bypass_flag=bypass_flag,
            control_command_flag=control_command_flag,
            reserved=reserved,
            spacecraft_id=spacecraft_id,
            virtual_channel_id=virtual_channel_id,
            frame_sequence_number=frame_sequence_number,
            data_field=data_field,
            fecf=fecf,
        )

    @classmethod
    def build(
        cls,
        *,
        spacecraft_id: int,
        virtual_channel_id: int,
        frame_sequence_number: int,
        payload: bytes,
        bypass_flag: bool = False,
        control_command_flag: bool = False,
        fecf: bytes | None = None,
    ) -> TcTransferFrame:
        return cls(
            spacecraft_id=spacecraft_id,
            virtual_channel_id=virtual_channel_id,
            frame_sequence_number=frame_sequence_number,
            bypass_flag=bypass_flag,
            control_command_flag=control_command_flag,
            data_field=payload,
            fecf=fecf,
        )
