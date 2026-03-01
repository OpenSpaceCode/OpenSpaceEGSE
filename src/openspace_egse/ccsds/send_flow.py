from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from .sdlp import TcTransferFrame
from .sdlp_uart import SdlpUartStreamSerializer
from .space_packet import SpacePacket


MAX_SEQUENCE_COUNT = 0x3FFF
MAX_FRAME_SEQUENCE_NUMBER = 0xFF

UINT8_MIN = 0
UINT8_MAX = 0xFF
UINT16_MAX = 0xFFFF


class SerialWriteLike(Protocol):
    def write(self, data: bytes) -> int | None:
        ...


class TcCommandName(str, Enum):
    PING = "ping"
    SET_MODE = "set_mode"
    RESET_SUBSYSTEM = "reset_subsystem"
    REQUEST_STATUS = "request_status"


@dataclass(slots=True, frozen=True)
class TcCommandDefinition:
    command: TcCommandName
    requires_parameter: bool
    parameter_min: int | None = None
    parameter_max: int | None = None


_TC_COMMAND_DEFINITIONS: dict[TcCommandName, TcCommandDefinition] = {
    TcCommandName.PING: TcCommandDefinition(
        command=TcCommandName.PING,
        requires_parameter=True,
        parameter_min=0,
        parameter_max=UINT16_MAX,
    ),
    TcCommandName.SET_MODE: TcCommandDefinition(
        command=TcCommandName.SET_MODE,
        requires_parameter=True,
        parameter_min=UINT8_MIN,
        parameter_max=UINT8_MAX,
    ),
    TcCommandName.RESET_SUBSYSTEM: TcCommandDefinition(
        command=TcCommandName.RESET_SUBSYSTEM,
        requires_parameter=True,
        parameter_min=UINT8_MIN,
        parameter_max=UINT8_MAX,
    ),
    TcCommandName.REQUEST_STATUS: TcCommandDefinition(
        command=TcCommandName.REQUEST_STATUS,
        requires_parameter=False,
    ),
}


@dataclass(slots=True, frozen=True)
class TcSendConfig:
    spacecraft_id: int
    virtual_channel_id: int
    space_packet_apid: int
    secondary_header_flag: bool = False
    fecf: bytes | None = None


@dataclass(slots=True, frozen=True)
class SentTcCommand:
    command: TcCommandName
    parameter: int | None
    command_payload: bytes
    space_packet: SpacePacket
    tc_transfer_frame: TcTransferFrame
    uart_bytes: bytes
    bytes_written: int


class TcCommandSender:
    def __init__(
        self,
        serial_port: SerialWriteLike,
        config: TcSendConfig,
        *,
        initial_packet_sequence_count: int = 0,
        initial_frame_sequence_number: int = 0,
    ) -> None:
        if not 0 <= initial_packet_sequence_count <= MAX_SEQUENCE_COUNT:
            raise ValueError("initial_packet_sequence_count out of range")
        if not 0 <= initial_frame_sequence_number <= MAX_FRAME_SEQUENCE_NUMBER:
            raise ValueError("initial_frame_sequence_number out of range")

        self._serial_port = serial_port
        self._config = config
        self._packet_sequence_count = initial_packet_sequence_count
        self._frame_sequence_number = initial_frame_sequence_number

    def send(
        self,
        command: TcCommandName | str,
        parameter: int | None = None,
    ) -> SentTcCommand:
        command_name = _normalize_command_name(command)
        command_payload = build_tc_command_payload(command_name, parameter)

        space_packet = SpacePacket.build_tc(
            apid=self._config.space_packet_apid,
            sequence_count=self._packet_sequence_count,
            payload=command_payload,
            secondary_header_flag=self._config.secondary_header_flag,
        )

        tc_transfer_frame = TcTransferFrame.build(
            spacecraft_id=self._config.spacecraft_id,
            virtual_channel_id=self._config.virtual_channel_id,
            frame_sequence_number=self._frame_sequence_number,
            payload=space_packet.encode(),
            fecf=self._config.fecf,
        )

        uart_bytes = SdlpUartStreamSerializer.serialize_tc(tc_transfer_frame)
        bytes_written_raw = self._serial_port.write(uart_bytes)
        bytes_written = len(uart_bytes) if bytes_written_raw is None else bytes_written_raw
        if bytes_written != len(uart_bytes):
            raise IOError("serial port write was incomplete")

        self._increment_counters()
        return SentTcCommand(
            command=command_name,
            parameter=parameter,
            command_payload=command_payload,
            space_packet=space_packet,
            tc_transfer_frame=tc_transfer_frame,
            uart_bytes=uart_bytes,
            bytes_written=bytes_written,
        )

    @property
    def packet_sequence_count(self) -> int:
        return self._packet_sequence_count

    @property
    def frame_sequence_number(self) -> int:
        return self._frame_sequence_number

    def _increment_counters(self) -> None:
        self._packet_sequence_count = (self._packet_sequence_count + 1) & MAX_SEQUENCE_COUNT
        self._frame_sequence_number = (
            self._frame_sequence_number + 1
        ) & MAX_FRAME_SEQUENCE_NUMBER


def available_tc_commands() -> tuple[str, ...]:
    return tuple(item.value for item in TcCommandName)


def tc_command_definition(command: TcCommandName | str) -> TcCommandDefinition:
    command_name = _normalize_command_name(command)
    return _TC_COMMAND_DEFINITIONS[command_name]


def build_tc_command_payload(
    command: TcCommandName | str,
    parameter: int | None = None,
) -> bytes:
    command_name = _normalize_command_name(command)
    definition = _TC_COMMAND_DEFINITIONS[command_name]

    if definition.requires_parameter and parameter is None:
        raise ValueError(f"Command '{command_name.value}' requires a parameter")
    if not definition.requires_parameter and parameter is not None:
        raise ValueError(f"Command '{command_name.value}' does not accept a parameter")

    if command_name == TcCommandName.PING:
        assert parameter is not None
        _validate_u16(parameter, name="parameter")
        return bytes((0x01,)) + parameter.to_bytes(2, "big")

    if command_name == TcCommandName.SET_MODE:
        assert parameter is not None
        _validate_u8(parameter, name="parameter")
        return bytes((0x02, parameter))

    if command_name == TcCommandName.RESET_SUBSYSTEM:
        assert parameter is not None
        _validate_u8(parameter, name="parameter")
        return bytes((0x03, parameter))

    if command_name == TcCommandName.REQUEST_STATUS:
        return bytes((0x04,))

    raise ValueError(f"Unsupported command: {command_name}")


def _normalize_command_name(command: TcCommandName | str) -> TcCommandName:
    if isinstance(command, TcCommandName):
        return command
    try:
        return TcCommandName(command)
    except ValueError as exc:
        raise ValueError(
            f"Unknown TC command '{command}'. Available: {', '.join(available_tc_commands())}"
        ) from exc


def _validate_u8(value: int, *, name: str) -> None:
    if not UINT8_MIN <= value <= UINT8_MAX:
        raise ValueError(f"{name} must be in range 0..255")


def _validate_u16(value: int, *, name: str) -> None:
    if not UINT8_MIN <= value <= UINT16_MAX:
        raise ValueError(f"{name} must be in range 0..65535")
