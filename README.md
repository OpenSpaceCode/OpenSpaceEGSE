# OpenSpaceEGSE

Python-based EGSE application for on-ground satellite testing.

Current scope:
- CCSDS Space Packet encode/decode
- TM/TC SDLP transfer frame encode/decode
- UART byte-stream framing + parser
- TC send pipeline and TM receive pipeline
- Desktop GUI (control + monitoring)

The `docs/` folder contains standards reference PDFs, including:
- `space_packet_ccsds.pdf`
- TM/TC SDLP related PDFs

---

## 1) Project Structure

```text
OpenSpaceEGSE/
├── docs/
├── src/
│   └── openspace_egse/
│       ├── config.py
│       ├── ccsds/
│       │   ├── __init__.py
│       │   ├── space_packet.py
│       │   ├── sdlp.py
│       │   ├── sdlp_uart.py
│       │   ├── send_flow.py
│       │   ├── receive_flow.py
│       │   └── telemetry.py
│       └── gui/
│           └── app.py
├── tests/
└── pyproject.toml
```

---

## 2) Installation & Run

### Requirements
- Python `>= 3.11`
- For GUI on Linux: `python3-tk` OS package must be installed

### Setup

```bash
python -m pip install -e .[dev,gui]
```

### Run GUI

```bash
openspace-egse-gui
```

### Running on WSL in Windows
Running app on WSL in Windows may cause problems with USB com connection in the App. Here is the step by step instruction to handle it.
1. Make sure you have usbipd installed in your system
```bash
winget install usbipd
```
2. Check list of USB devices and search for your device
```bash
usbipd list
```
3. Bind the device (i.e. 1-2)
```bash
usbipd bind --busid 1-2
```
4. Attach the device to WSL (i.e. 1-2)
```bash
usbipd attach --wsl --busid 1-2
```

You can the check if the device is visible in WSL using commands:
```bash
lsusb
```
or
```bash
ls /dev/tty*
```
It may show up as /dev/ttyACM*.

### Run tests

```bash
pytest
```

---

## 3) Protocol Stack Implemented

End-to-end flow:

### TX (TC to OBC)
1. Build TC command payload
2. Wrap in CCSDS Space Packet (`packet_type = TELECOMMAND`)
3. Wrap in SDLP TC Transfer Frame
4. Wrap in UART stream envelope + SLIP escaping
5. Write to serial port

### RX (TM from OBC)
1. Read UART bytes
2. SLIP de-frame + parse UART envelope
3. Decode SDLP TM frame
4. Extract CCSDS Space Packet(s)
5. Decode telemetry payload and display/update charts

---

## 4) CCSDS Space Packet

Implemented in `src/openspace_egse/ccsds/space_packet.py`.

Primary header length: `6 bytes`.

Supported fields:
- `version` (3 bits)
- `packet_type` (`TELEMETRY` / `TELECOMMAND`)
- `secondary_header_flag`
- `apid` (11 bits)
- `sequence_flags` (2 bits)
- `sequence_count` (14 bits)
- `data_length` (`len(data_field) - 1`)

Validation includes APID, sequence count, payload length consistency, and bytes-like checks.

### Example

```python
from openspace_egse.ccsds import SpacePacket

packet = SpacePacket.build_tc(
		apid=100,
		sequence_count=5,
		payload=b"\x01\x02\x03",
)

raw = packet.encode()
decoded = SpacePacket.decode(raw)
assert decoded == packet
```

---

## 5) SDLP TM/TC Transfer Frames

Implemented in `src/openspace_egse/ccsds/sdlp.py`.

### TM Transfer Frame (`TmTransferFrame`)
- Primary header length: `6 bytes`
- Supports:
	- `spacecraft_id`, `virtual_channel_id`
	- `master_channel_frame_count`, `virtual_channel_frame_count`
	- `first_header_pointer`
	- `ocf` (optional, 4 bytes)
	- `fecf` (optional, 2 bytes)

### TC Transfer Frame (`TcTransferFrame`)
- Primary header length: `5 bytes`
- Supports:
	- `spacecraft_id`, `virtual_channel_id`, `frame_sequence_number`
	- `bypass_flag`, `control_command_flag`
	- frame length field consistency checks
	- optional `fecf` (2 bytes)

Both TM/TC include strict encode/decode length validations.

---

## 6) UART Framing (Stream Boundary Handling)

Implemented in `src/openspace_egse/ccsds/sdlp_uart.py`.

Important: this is a **project transport envelope** (not a CCSDS standard field layout).

### Envelope payload (inside SLIP)
- Byte 0: frame type (`1=TM`, `2=TC`)
- Byte 1: flags (`bit0 = has_fecf`)
- Bytes 2..3: SDLP frame length (`uint16`, big-endian)
- Remaining: encoded SDLP frame bytes

### SLIP framing
- `END=0xC0`, `ESC=0xDB`
- Escapes handled with `0xDC` / `0xDD`
- Parser supports fragmented chunks and multiple concatenated frames

---

## 7) TC Command Creation & Sending

Implemented in `src/openspace_egse/ccsds/send_flow.py`.

Main API:
- `TcCommandSender.send(command, parameter=None)`
- `TcSendConfig` for SCID/VCID/APID settings

Built-in commands:

| Command           | Payload format             |
| ----------------- | -------------------------- |
| `ping`            | `0x01 + uint16(parameter)` |
| `set_mode`        | `0x02 + uint8(parameter)`  |
| `reset_subsystem` | `0x03 + uint8(parameter)`  |
| `request_status`  | `0x04`                     |

Sequence counters are incremented automatically after successful write.

### Example

```python
from openspace_egse.ccsds import TcCommandSender, TcSendConfig

sender = TcCommandSender(
		serial_port=my_serial,
		config=TcSendConfig(
				spacecraft_id=1,
				virtual_channel_id=0,
				space_packet_apid=100,
		),
)

sender.send("set_mode", 2)
```

---

## 8) TM Reception & Decoding

Implemented in `src/openspace_egse/ccsds/receive_flow.py`.

Main API:
- `SdlpSpacePacketReceiver.process_uart_bytes(...)`
- `SdlpSpacePacketReceiver.process_serial_once(...)`
- `receive_and_print_once(...)`

Behavior:
- Parses UART stream to TM/TC SDLP frames
- Extracts Space Packet(s) from frame data field
- For TM uses `first_header_pointer` as packet start offset
- Returns decoded SpacePacket objects with frame type context

---

## 9) Telemetry Payload Format (Current GUI Decoder)

Implemented in `src/openspace_egse/ccsds/telemetry.py`.

Current expected TM payload layout (`>= 7 bytes`):

| Offset | Size | Meaning          | Conversion                                      |
| ------ | ---: | ---------------- | ----------------------------------------------- |
| 0      |    1 | status code      | mapped to text (`BOOT/IDLE/NOMINAL/SAFE/FAULT`) |
| 1..2   |    2 | temperature      | signed int16 / 100 -> °C                        |
| 3..4   |    2 | voltage          | uint16 / 1000 -> V                              |
| 5..6   |    2 | battery capacity | uint16 / 10 -> %                                |

---

## 10) GUI Features

Implemented in `src/openspace_egse/gui/app.py`.

### Control panel
- Serial connect/disconnect
- TC command selection + parameter input
- Send TC button
- Simulation tools:
	- single telemetry injection
	- auto simulation start/stop
	- simulation frequency toggle

### Monitoring panel
- Live charts:
	- temperature
	- voltage
	- battery capacity
- State text fields:
	- status
	- latest values
	- last update time
- Clear telemetry data button

### Event log
- On-screen event log
- Optional log-to-file
- Default file: `logs/egse_events.log` (repo-local)

---

## 11) Central Configuration

All runtime/configurable parameters are in:
- `src/openspace_egse/config.py`

This includes serial defaults, GUI timings/history, simulation waveform parameters, APIDs/SCID/VCID defaults, and event log defaults.

---

## 12) Extending with Your Own TC Commands

Edit `src/openspace_egse/ccsds/send_flow.py`:

1. Add enum value in `TcCommandName`
2. Add metadata in `_TC_COMMAND_DEFINITIONS`
3. Add payload encoder branch in `build_tc_command_payload(...)`

If parameter behavior changes, GUI control logic automatically adapts via `tc_command_definition(...)`.

Tip: keep command IDs (`0x01`, `0x02`, ...) stable and documented.

---

## 13) Extending with Your Own TM Telemetry

Edit `src/openspace_egse/ccsds/telemetry.py`:

1. Define your payload field offsets
2. Decode raw bytes into engineering units
3. Update status map if needed

Then update GUI rendering in `src/openspace_egse/gui/app.py` if you add new displayed fields or plots.

---

## 14) Notes

- This repository currently focuses on a clear, testable baseline rather than complete mission-specific protocol coverage.
- `sdlp_uart.py` transport envelope is intentionally simple for UART stream robustness and development velocity.
- Unit tests cover encode/decode, stream boundary handling, receive/send pipelines, and telemetry decoding.
