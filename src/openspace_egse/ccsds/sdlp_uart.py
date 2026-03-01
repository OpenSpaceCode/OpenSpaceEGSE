from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from .sdlp import TcTransferFrame, TmTransferFrame


SLIP_END = 0xC0
SLIP_ESC = 0xDB
SLIP_ESC_END = 0xDC
SLIP_ESC_ESC = 0xDD

UART_HEADER_LENGTH = 4


class SdlpFrameType(IntEnum):
    TM = 1
    TC = 2


@dataclass(slots=True, frozen=True)
class ParsedSdlpFrame:
    frame_type: SdlpFrameType
    frame: TmTransferFrame | TcTransferFrame
    has_fecf: bool


class SdlpUartStreamSerializer:
    @staticmethod
    def serialize_tm(frame: TmTransferFrame) -> bytes:
        payload = frame.encode()
        flags = 1 if frame.fecf is not None else 0
        return _slip_encode(_build_uart_payload(SdlpFrameType.TM, flags, payload))

    @staticmethod
    def serialize_tc(frame: TcTransferFrame) -> bytes:
        payload = frame.encode()
        flags = 1 if frame.fecf is not None else 0
        return _slip_encode(_build_uart_payload(SdlpFrameType.TC, flags, payload))


class SdlpUartStreamParser:
    def __init__(self) -> None:
        self._in_frame = False
        self._escape_next = False
        self._frame_buffer = bytearray()

    def feed(self, uart_bytes: bytes) -> list[ParsedSdlpFrame]:
        if not isinstance(uart_bytes, (bytes, bytearray)):
            raise TypeError("uart_bytes must be bytes-like")

        parsed: list[ParsedSdlpFrame] = []
        for item in uart_bytes:
            if item == SLIP_END:
                if self._in_frame and self._frame_buffer:
                    maybe = self._parse_slip_payload(bytes(self._frame_buffer))
                    if maybe is not None:
                        parsed.append(maybe)
                self._in_frame = True
                self._escape_next = False
                self._frame_buffer.clear()
                continue

            if not self._in_frame:
                continue

            if self._escape_next:
                if item == SLIP_ESC_END:
                    self._frame_buffer.append(SLIP_END)
                elif item == SLIP_ESC_ESC:
                    self._frame_buffer.append(SLIP_ESC)
                else:
                    self._in_frame = False
                    self._escape_next = False
                    self._frame_buffer.clear()
                    continue
                self._escape_next = False
                continue

            if item == SLIP_ESC:
                self._escape_next = True
                continue

            self._frame_buffer.append(item)

        return parsed

    @staticmethod
    def _parse_slip_payload(payload: bytes) -> ParsedSdlpFrame | None:
        if len(payload) < UART_HEADER_LENGTH:
            return None

        frame_type_raw = payload[0]
        flags = payload[1]
        frame_length = int.from_bytes(payload[2:4], "big")
        frame_bytes = payload[4:]
        if len(frame_bytes) != frame_length:
            return None

        try:
            frame_type = SdlpFrameType(frame_type_raw)
        except ValueError:
            return None

        has_fecf = bool(flags & 0x01)

        try:
            if frame_type == SdlpFrameType.TM:
                frame = TmTransferFrame.decode(frame_bytes, has_fecf=has_fecf)
            else:
                frame = TcTransferFrame.decode(frame_bytes, has_fecf=has_fecf)
        except (TypeError, ValueError):
            return None

        return ParsedSdlpFrame(frame_type=frame_type, frame=frame, has_fecf=has_fecf)


def _build_uart_payload(
    frame_type: SdlpFrameType,
    flags: int,
    frame_bytes: bytes,
) -> bytes:
    if len(frame_bytes) > 0xFFFF:
        raise ValueError("SDLP frame is too large for UART stream length field")
    return (
        bytes([int(frame_type), flags & 0xFF])
        + len(frame_bytes).to_bytes(2, "big")
        + frame_bytes
    )


def _slip_encode(payload: bytes) -> bytes:
    encoded = bytearray([SLIP_END])
    for item in payload:
        if item == SLIP_END:
            encoded.extend((SLIP_ESC, SLIP_ESC_END))
        elif item == SLIP_ESC:
            encoded.extend((SLIP_ESC, SLIP_ESC_ESC))
        else:
            encoded.append(item)
    encoded.append(SLIP_END)
    return bytes(encoded)
