from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


TELEMETRY_MIN_PAYLOAD_LENGTH = 7
STATUS_INDEX = 0
TEMPERATURE_START = 1
TEMPERATURE_END = 3
VOLTAGE_START = 3
VOLTAGE_END = 5
CAPACITY_START = 5
CAPACITY_END = 7

STATUS_TEXT_MAP = {
    0: "BOOT",
    1: "IDLE",
    2: "NOMINAL",
    3: "SAFE",
    4: "FAULT",
}


@dataclass(slots=True, frozen=True)
class TelemetrySample:
    timestamp: datetime
    status_code: int
    status_text: str
    temperature_c: float
    voltage_v: float
    battery_capacity_pct: float


def decode_telemetry_payload(payload: bytes) -> TelemetrySample:
    if not isinstance(payload, (bytes, bytearray)):
        raise TypeError("payload must be bytes-like")
    if len(payload) < TELEMETRY_MIN_PAYLOAD_LENGTH:
        raise ValueError("telemetry payload is too short")

    status_code = int(payload[STATUS_INDEX])
    temperature_raw = int.from_bytes(
        payload[TEMPERATURE_START:TEMPERATURE_END],
        byteorder="big",
        signed=True,
    )
    voltage_raw = int.from_bytes(payload[VOLTAGE_START:VOLTAGE_END], byteorder="big")
    capacity_raw = int.from_bytes(payload[CAPACITY_START:CAPACITY_END], byteorder="big")

    return TelemetrySample(
        timestamp=datetime.now(),
        status_code=status_code,
        status_text=STATUS_TEXT_MAP.get(status_code, f"UNKNOWN({status_code})"),
        temperature_c=temperature_raw / 100.0,
        voltage_v=voltage_raw / 1000.0,
        battery_capacity_pct=capacity_raw / 10.0,
    )
