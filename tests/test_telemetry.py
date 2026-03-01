import pytest

from openspace_egse.ccsds import decode_telemetry_payload


def test_decode_telemetry_payload_nominal() -> None:
    payload = bytes(
        [
            2,
            0x09,
            0xC4,
            0x13,
            0xBA,
            0x03,
            0x84,
        ]
    )
    sample = decode_telemetry_payload(payload)

    assert sample.status_code == 2
    assert sample.status_text == "NOMINAL"
    assert sample.temperature_c == 25.0
    assert sample.voltage_v == 5.05
    assert sample.battery_capacity_pct == 90.0


def test_decode_telemetry_payload_unknown_status() -> None:
    payload = bytes([99, 0x00, 0x00, 0x00, 0x64, 0x00, 0x64])
    sample = decode_telemetry_payload(payload)
    assert sample.status_text == "UNKNOWN(99)"


def test_decode_telemetry_payload_validation() -> None:
    with pytest.raises(ValueError, match="too short"):
        decode_telemetry_payload(b"\x01\x00")

    with pytest.raises(TypeError, match="bytes-like"):
        decode_telemetry_payload("abc")  # type: ignore[arg-type]
