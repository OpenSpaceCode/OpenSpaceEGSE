from __future__ import annotations

import queue
import threading
import time
from collections import deque
from datetime import datetime

try:
    import tkinter as tk
    from tkinter import messagebox, ttk

    TK_AVAILABLE = True
except ImportError:
    tk = None
    messagebox = None
    ttk = None
    TK_AVAILABLE = False

try:
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure

    MATPLOTLIB_AVAILABLE = True
except ImportError:
    FigureCanvasTkAgg = None
    Figure = None
    MATPLOTLIB_AVAILABLE = False

from openspace_egse.config import (
    CCSDS_DEFAULT_SPACECRAFT_ID,
    CCSDS_DEFAULT_TC_APID,
    CCSDS_DEFAULT_TM_APID,
    CCSDS_DEFAULT_VIRTUAL_CHANNEL_ID,
    EGSE_SERIAL_BAUDRATE_DEFAULT,
    EGSE_SERIAL_MAX_READ_SIZE,
    EGSE_SERIAL_PORT_DEFAULT,
    GUI_PLOT_HISTORY_LENGTH,
    GUI_RX_POLL_INTERVAL_S,
    GUI_SIM_FREQUENCY_DEFAULT_INDEX,
    GUI_SIM_FREQUENCY_OPTIONS_HZ,
    GUI_UPDATE_INTERVAL_MS,
    SIM_CAPACITY_BASE_DECI_PCT,
    SIM_CAPACITY_DECREMENT_PER_SAMPLE,
    SIM_CAPACITY_SPAN_SAMPLES,
    SIM_TELEMETRY_STATUS_CYCLE,
    SIM_TEMPERATURE_BASE_CENTI_C,
    SIM_TEMPERATURE_SPAN_SAMPLES,
    SIM_TEMPERATURE_STEP_CENTI_C,
    SIM_VOLTAGE_BASE_MV,
    SIM_VOLTAGE_SPAN_SAMPLES,
    SIM_VOLTAGE_STEP_MV,
)

from openspace_egse.ccsds import (
    PacketType,
    SpacePacket,
    SdlpSpacePacketReceiver,
    SdlpUartStreamSerializer,
    TcCommandSender,
    TcSendConfig,
    TmTransferFrame,
    available_tc_commands,
    decode_telemetry_payload,
    tc_command_definition,
)

try:
    import serial
    from serial import SerialException
except ImportError:
    serial = None
    SerialException = Exception


COLOR_BG_MAIN = "#EEF2F8"
COLOR_BG_SURFACE = "#F8FAFD"
COLOR_BG_SURFACE_ALT = "#FFFFFF"
COLOR_BORDER = "#C8D3E3"
COLOR_TEXT_PRIMARY = "#1E2A3B"
COLOR_TEXT_MUTED = "#5B6C84"
COLOR_ACCENT = "#1E6BD6"
COLOR_ACCENT_HOVER = "#2F7CE4"
COLOR_DANGER = "#B84E4E"
COLOR_DANGER_HOVER = "#C96060"

CHART_COLOR_TEMP = "#D64545"
CHART_COLOR_VOLTAGE = "#1E6BD6"
CHART_COLOR_CAPACITY = "#2E8B57"
CHART_GRID_COLOR = "#D9E2EF"


class EgseGuiApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("OpenSpaceEGSE")
        self.root.geometry("1250x760")
        self.root.configure(bg=COLOR_BG_MAIN)

        self._serial_port = None
        self._sender: TcCommandSender | None = None
        self._receiver = SdlpSpacePacketReceiver()

        self._rx_queue: queue.Queue = queue.Queue()
        self._rx_stop_event = threading.Event()
        self._rx_thread: threading.Thread | None = None

        self._sample_index = 0
        self._sim_tm_packet_sequence = 0
        self._sim_tm_frame_count = 0
        self._auto_sim_running = False
        self._auto_sim_after_id: str | None = None
        self._sim_frequency_index = GUI_SIM_FREQUENCY_DEFAULT_INDEX
        self._x = deque(maxlen=GUI_PLOT_HISTORY_LENGTH)
        self._temperature = deque(maxlen=GUI_PLOT_HISTORY_LENGTH)
        self._voltage = deque(maxlen=GUI_PLOT_HISTORY_LENGTH)
        self._capacity = deque(maxlen=GUI_PLOT_HISTORY_LENGTH)

        if not GUI_SIM_FREQUENCY_OPTIONS_HZ:
            raise ValueError("GUI_SIM_FREQUENCY_OPTIONS_HZ must not be empty")
        if not 0 <= self._sim_frequency_index < len(GUI_SIM_FREQUENCY_OPTIONS_HZ):
            self._sim_frequency_index = 0

        self._setup_style()
        self._build_layout()
        self._start_rx_thread()
        self.root.after(GUI_UPDATE_INTERVAL_MS, self._process_rx_queue)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _setup_style(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")

        self.root.option_add("*Font", "TkDefaultFont 10")

        style.configure("TFrame", background=COLOR_BG_MAIN)
        style.configure("App.TFrame", background=COLOR_BG_MAIN)
        style.configure("Card.TFrame", background=COLOR_BG_SURFACE)

        style.configure(
            "TLabel",
            background=COLOR_BG_SURFACE,
            foreground=COLOR_TEXT_PRIMARY,
        )
        style.configure(
            "Muted.TLabel",
            background=COLOR_BG_SURFACE,
            foreground=COLOR_TEXT_MUTED,
        )

        style.configure(
            "Card.TLabelframe",
            background=COLOR_BG_SURFACE,
            bordercolor=COLOR_BORDER,
            darkcolor=COLOR_BORDER,
            lightcolor=COLOR_BORDER,
            relief="solid",
            borderwidth=1,
            padding=10,
        )
        style.configure(
            "Card.TLabelframe.Label",
            background=COLOR_BG_SURFACE,
            foreground=COLOR_TEXT_PRIMARY,
            font=("TkDefaultFont", 10, "bold"),
        )

        style.configure(
            "Primary.TButton",
            background=COLOR_ACCENT,
            foreground="#FFFFFF",
            borderwidth=0,
            padding=(10, 7),
            focusthickness=0,
        )
        style.map(
            "Primary.TButton",
            background=[("active", COLOR_ACCENT_HOVER), ("pressed", COLOR_ACCENT_HOVER)],
            foreground=[("disabled", COLOR_TEXT_MUTED)],
        )

        style.configure(
            "Danger.TButton",
            background=COLOR_DANGER,
            foreground="#FFFFFF",
            borderwidth=0,
            padding=(10, 7),
            focusthickness=0,
        )
        style.map(
            "Danger.TButton",
            background=[("active", COLOR_DANGER_HOVER), ("pressed", COLOR_DANGER_HOVER)],
            foreground=[("disabled", COLOR_TEXT_MUTED)],
        )

        style.configure(
            "Secondary.TButton",
            background=COLOR_BG_SURFACE_ALT,
            foreground=COLOR_TEXT_PRIMARY,
            bordercolor=COLOR_BORDER,
            borderwidth=1,
            padding=(10, 7),
        )
        style.map(
            "Secondary.TButton",
            background=[("active", "#E9F1FC"), ("pressed", "#E9F1FC")],
            foreground=[("disabled", COLOR_TEXT_MUTED)],
        )

        style.configure(
            "TEntry",
            fieldbackground=COLOR_BG_SURFACE_ALT,
            foreground=COLOR_TEXT_PRIMARY,
            insertcolor=COLOR_TEXT_PRIMARY,
            bordercolor=COLOR_BORDER,
            lightcolor=COLOR_BORDER,
            darkcolor=COLOR_BORDER,
            padding=5,
        )
        style.configure(
            "TCombobox",
            fieldbackground=COLOR_BG_SURFACE_ALT,
            background=COLOR_BG_SURFACE_ALT,
            foreground=COLOR_TEXT_PRIMARY,
            arrowcolor=COLOR_TEXT_PRIMARY,
            bordercolor=COLOR_BORDER,
            lightcolor=COLOR_BORDER,
            darkcolor=COLOR_BORDER,
            padding=4,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", COLOR_BG_SURFACE_ALT)],
            background=[("readonly", COLOR_BG_SURFACE_ALT)],
            foreground=[("readonly", COLOR_TEXT_PRIMARY)],
            selectbackground=[("readonly", COLOR_BG_SURFACE_ALT)],
            selectforeground=[("readonly", COLOR_TEXT_PRIMARY)],
        )

        style.configure("TPanedwindow", background=COLOR_BG_MAIN)

    def _build_layout(self) -> None:
        container = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        container.pack(fill=tk.BOTH, expand=True)

        self.control_frame = ttk.Frame(container, padding=12, style="App.TFrame")
        self.monitor_frame = ttk.Frame(container, padding=12, style="App.TFrame")
        container.add(self.control_frame, weight=2)
        container.add(self.monitor_frame, weight=3)

        self._build_control_panel()
        self._build_monitor_panel()

    def _build_control_panel(self) -> None:
        conn_group = ttk.LabelFrame(
            self.control_frame,
            text="Connection",
            style="Card.TLabelframe",
            padding=10,
        )
        conn_group.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(conn_group, text="Port").grid(row=0, column=0, sticky=tk.W)
        self.port_var = tk.StringVar(value=EGSE_SERIAL_PORT_DEFAULT)
        ttk.Entry(conn_group, textvariable=self.port_var, width=18).grid(
            row=0, column=1, sticky=tk.W, padx=(6, 0)
        )

        ttk.Label(conn_group, text="Baud").grid(row=1, column=0, sticky=tk.W, pady=(6, 0))
        self.baud_var = tk.StringVar(value=str(EGSE_SERIAL_BAUDRATE_DEFAULT))
        ttk.Entry(conn_group, textvariable=self.baud_var, width=18).grid(
            row=1, column=1, sticky=tk.W, padx=(6, 0), pady=(6, 0)
        )

        self.connection_status_var = tk.StringVar(value="Disconnected")
        ttk.Label(
            conn_group,
            textvariable=self.connection_status_var,
        ).grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(8, 0))

        button_row = ttk.Frame(conn_group, style="Card.TFrame")
        button_row.grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=(8, 0))
        ttk.Button(
            button_row,
            text="Connect",
            command=self._connect,
            style="Primary.TButton",
        ).pack(
            side=tk.LEFT
        )
        ttk.Button(
            button_row,
            text="Disconnect",
            command=self._disconnect,
            style="Danger.TButton",
        ).pack(
            side=tk.LEFT, padx=(8, 0)
        )

        tc_group = ttk.LabelFrame(
            self.control_frame,
            text="TC Control",
            style="Card.TLabelframe",
            padding=10,
        )
        tc_group.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(tc_group, text="SCID").grid(row=0, column=0, sticky=tk.W)
        self.scid_var = tk.StringVar(value=str(CCSDS_DEFAULT_SPACECRAFT_ID))
        ttk.Entry(tc_group, textvariable=self.scid_var, width=10).grid(
            row=0, column=1, sticky=tk.W, padx=(6, 0)
        )

        ttk.Label(tc_group, text="VCID").grid(row=1, column=0, sticky=tk.W, pady=(6, 0))
        self.vcid_var = tk.StringVar(value=str(CCSDS_DEFAULT_VIRTUAL_CHANNEL_ID))
        ttk.Entry(tc_group, textvariable=self.vcid_var, width=10).grid(
            row=1, column=1, sticky=tk.W, padx=(6, 0), pady=(6, 0)
        )

        ttk.Label(tc_group, text="TC APID").grid(row=2, column=0, sticky=tk.W, pady=(6, 0))
        self.tc_apid_var = tk.StringVar(value=str(CCSDS_DEFAULT_TC_APID))
        ttk.Entry(tc_group, textvariable=self.tc_apid_var, width=10).grid(
            row=2, column=1, sticky=tk.W, padx=(6, 0), pady=(6, 0)
        )

        ttk.Label(tc_group, text="TM APID").grid(row=3, column=0, sticky=tk.W, pady=(6, 0))
        self.tm_apid_var = tk.StringVar(value=str(CCSDS_DEFAULT_TM_APID))
        ttk.Entry(tc_group, textvariable=self.tm_apid_var, width=10).grid(
            row=3, column=1, sticky=tk.W, padx=(6, 0), pady=(6, 0)
        )

        ttk.Label(tc_group, text="Command").grid(row=4, column=0, sticky=tk.W, pady=(8, 0))
        self.command_var = tk.StringVar(value=available_tc_commands()[0])
        self.command_box = ttk.Combobox(
            tc_group,
            textvariable=self.command_var,
            values=available_tc_commands(),
            state="readonly",
            width=20,
        )
        self.command_box.grid(row=4, column=1, sticky=tk.W, padx=(6, 0), pady=(8, 0))
        self.command_box.bind("<<ComboboxSelected>>", self._on_command_changed)

        ttk.Label(tc_group, text="Parameter").grid(row=5, column=0, sticky=tk.W, pady=(6, 0))
        self.parameter_var = tk.StringVar(value="0")
        self.parameter_entry = ttk.Entry(
            tc_group,
            textvariable=self.parameter_var,
            width=20,
        )
        self.parameter_entry.grid(row=5, column=1, sticky=tk.W, padx=(6, 0), pady=(6, 0))
        self.parameter_hint_var = tk.StringVar(value="")
        ttk.Label(tc_group, textvariable=self.parameter_hint_var).grid(
            row=6,
            column=0,
            columnspan=2,
            sticky=tk.W,
            pady=(6, 0),
        )

        ttk.Button(
            tc_group,
            text="Send TC",
            command=self._send_tc,
            style="Primary.TButton",
        ).grid(
            row=7,
            column=0,
            columnspan=2,
            sticky=tk.W,
            pady=(10, 0),
        )

        sim_group = ttk.LabelFrame(
            self.control_frame,
            text="Simulation",
            style="Card.TLabelframe",
            padding=10,
        )
        sim_group.pack(fill=tk.X, pady=(0, 8))
        ttk.Button(
            sim_group,
            text="Inject Simulated Telemetry",
            command=self._inject_simulated_telemetry,
            style="Secondary.TButton",
        ).pack(anchor=tk.W)
        self.sim_frequency_button = ttk.Button(
            sim_group,
            text=self._sim_frequency_button_text(),
            command=self._toggle_sim_frequency,
            style="Secondary.TButton",
        )
        self.sim_frequency_button.pack(anchor=tk.W, pady=(6, 0))
        self.auto_sim_button = ttk.Button(
            sim_group,
            text=self._auto_sim_button_text(),
            command=self._toggle_auto_simulation,
            style="Secondary.TButton",
        )
        self.auto_sim_button.pack(anchor=tk.W, pady=(6, 0))
        ttk.Label(
            sim_group,
            text="Builds TM frame and feeds it to receive pipeline",
            style="Muted.TLabel",
        ).pack(anchor=tk.W, pady=(6, 0))

        log_group = ttk.LabelFrame(
            self.control_frame,
            text="Event Log",
            style="Card.TLabelframe",
            padding=10,
        )
        log_group.pack(fill=tk.BOTH, expand=True)
        self.log_text = tk.Text(
            log_group,
            height=24,
            state=tk.DISABLED,
            bg=COLOR_BG_SURFACE_ALT,
            fg=COLOR_TEXT_PRIMARY,
            insertbackground=COLOR_TEXT_PRIMARY,
            highlightthickness=1,
            highlightbackground=COLOR_BORDER,
            relief="flat",
            padx=8,
            pady=8,
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

        self._on_command_changed()

    def _build_monitor_panel(self) -> None:
        status_group = ttk.LabelFrame(
            self.monitor_frame,
            text="State",
            style="Card.TLabelframe",
            padding=10,
        )
        status_group.pack(fill=tk.X)

        status_header = ttk.Frame(status_group, style="Card.TFrame")
        status_header.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(
            status_header,
            text="Clear Telemetry Data",
            command=self._clear_telemetry_data,
            style="Secondary.TButton",
        ).pack(side=tk.RIGHT)

        self.state_status_var = tk.StringVar(value="Status: -")
        self.state_temp_var = tk.StringVar(value="Temperature: -")
        self.state_voltage_var = tk.StringVar(value="Voltage: -")
        self.state_capacity_var = tk.StringVar(value="Battery Capacity: -")
        self.state_update_var = tk.StringVar(value="Last Update: -")

        ttk.Label(status_group, textvariable=self.state_status_var).pack(anchor=tk.W)
        ttk.Label(status_group, textvariable=self.state_temp_var).pack(anchor=tk.W)
        ttk.Label(status_group, textvariable=self.state_voltage_var).pack(anchor=tk.W)
        ttk.Label(status_group, textvariable=self.state_capacity_var).pack(anchor=tk.W)
        ttk.Label(status_group, textvariable=self.state_update_var).pack(anchor=tk.W)

        charts_group = ttk.LabelFrame(
            self.monitor_frame,
            text="Telemetry Charts",
            style="Card.TLabelframe",
            padding=10,
        )
        charts_group.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

        self.figure = Figure(figsize=(8.5, 6.5), dpi=100)
        self.figure.patch.set_facecolor(COLOR_BG_SURFACE)
        self.ax_temp = self.figure.add_subplot(311)
        self.ax_voltage = self.figure.add_subplot(312)
        self.ax_capacity = self.figure.add_subplot(313)

        self.temp_line, = self.ax_temp.plot([], [], color=CHART_COLOR_TEMP, linewidth=2.0)
        self.voltage_line, = self.ax_voltage.plot([], [], color=CHART_COLOR_VOLTAGE, linewidth=2.0)
        self.capacity_line, = self.ax_capacity.plot([], [], color=CHART_COLOR_CAPACITY, linewidth=2.0)

        self.ax_temp.set_title("Temperature [°C]")
        self.ax_voltage.set_title("Voltage [V]")
        self.ax_capacity.set_title("Battery Capacity [%]")
        self.ax_capacity.set_xlabel("Sample")

        for axis in (self.ax_temp, self.ax_voltage, self.ax_capacity):
            axis.set_facecolor(COLOR_BG_SURFACE)
            axis.grid(True, color=CHART_GRID_COLOR, linewidth=0.8, alpha=0.7)
            axis.tick_params(colors=COLOR_TEXT_MUTED, labelsize=9)
            axis.xaxis.label.set_color(COLOR_TEXT_MUTED)
            axis.yaxis.label.set_color(COLOR_TEXT_MUTED)
            axis.title.set_color(COLOR_TEXT_PRIMARY)
            for spine in axis.spines.values():
                spine.set_color(COLOR_BORDER)

        self.figure.tight_layout()
        self.canvas = FigureCanvasTkAgg(self.figure, master=charts_group)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def _connect(self) -> None:
        if serial is None:
            messagebox.showerror(
                "Missing dependency",
                "pyserial is not installed. Install with: pip install pyserial",
            )
            return
        if self._serial_port is not None:
            messagebox.showinfo("Connection", "Already connected")
            return

        try:
            port = self.port_var.get().strip()
            baudrate = int(self.baud_var.get().strip(), 0)
            self._serial_port = serial.Serial(port=port, baudrate=baudrate, timeout=0)

            config = TcSendConfig(
                spacecraft_id=int(self.scid_var.get(), 0),
                virtual_channel_id=int(self.vcid_var.get(), 0),
                space_packet_apid=int(self.tc_apid_var.get(), 0),
            )
            self._sender = TcCommandSender(self._serial_port, config)

            self.connection_status_var.set(f"Connected: {port} @ {baudrate}")
            self._log(f"Connected to {port} @ {baudrate}")
        except (ValueError, SerialException) as exc:
            self._serial_port = None
            self._sender = None
            messagebox.showerror("Connection failed", str(exc))

    def _disconnect(self) -> None:
        if self._serial_port is None:
            return
        try:
            self._serial_port.close()
        except Exception:
            pass
        self._serial_port = None
        self._sender = None
        self.connection_status_var.set("Disconnected")
        self._log("Disconnected")

    def _on_command_changed(self, *_args) -> None:
        command_name = self.command_var.get()
        definition = tc_command_definition(command_name)

        if definition.requires_parameter:
            self.parameter_entry.configure(state=tk.NORMAL)
            if definition.parameter_min is not None and definition.parameter_max is not None:
                self.parameter_hint_var.set(
                    f"Parameter range: {definition.parameter_min}..{definition.parameter_max}"
                )
            else:
                self.parameter_hint_var.set("Parameter required")
        else:
            self.parameter_entry.configure(state=tk.DISABLED)
            self.parameter_hint_var.set("No parameter required")

    def _send_tc(self) -> None:
        if self._sender is None:
            messagebox.showwarning("Not connected", "Connect UART first")
            return

        command_name = self.command_var.get()
        definition = tc_command_definition(command_name)

        try:
            parameter: int | None = None
            if definition.requires_parameter:
                parameter_text = self.parameter_var.get().strip()
                if not parameter_text:
                    raise ValueError("Parameter is required")
                parameter = int(parameter_text, 0)

            sent = self._sender.send(command_name, parameter)
            self._log(
                f"Sent {sent.command.value} param={sent.parameter} "
                f"seq={sent.space_packet.sequence_count} "
                f"frame_seq={sent.tc_transfer_frame.frame_sequence_number}"
            )
        except (ValueError, OSError) as exc:
            messagebox.showerror("Send failed", str(exc))

    def _inject_simulated_telemetry(self) -> None:
        try:
            tm_apid = int(self.tm_apid_var.get(), 0)
            spacecraft_id = int(self.scid_var.get(), 0)
            virtual_channel_id = int(self.vcid_var.get(), 0)
        except ValueError as exc:
            messagebox.showerror("Simulation failed", f"Invalid numeric field: {exc}")
            return

        payload = self._build_simulated_telemetry_payload()
        space_packet = SpacePacket.build_tm(
            apid=tm_apid,
            sequence_count=self._sim_tm_packet_sequence,
            payload=payload,
        )
        tm_frame = TmTransferFrame.build(
            spacecraft_id=spacecraft_id,
            virtual_channel_id=virtual_channel_id,
            master_channel_frame_count=self._sim_tm_frame_count,
            virtual_channel_frame_count=self._sim_tm_frame_count,
            payload=space_packet.encode(),
            first_header_pointer=0,
        )
        uart_stream = SdlpUartStreamSerializer.serialize_tm(tm_frame)

        decoded_packets = self._receiver.process_uart_bytes(uart_stream)
        for decoded in decoded_packets:
            self._handle_decoded_packet(decoded)

        self._sim_tm_packet_sequence = (self._sim_tm_packet_sequence + 1) & 0x3FFF
        self._sim_tm_frame_count = (self._sim_tm_frame_count + 1) & 0xFF
        self._log(
            "Injected simulated telemetry "
            f"temp={payload[1:3].hex().upper()} "
            f"volt={payload[3:5].hex().upper()} "
            f"cap={payload[5:7].hex().upper()}"
        )

    def _build_simulated_telemetry_payload(self) -> bytes:
        index = self._sim_tm_packet_sequence
        status_code = index % SIM_TELEMETRY_STATUS_CYCLE

        temperature_centi_c = SIM_TEMPERATURE_BASE_CENTI_C + (
            (index % SIM_TEMPERATURE_SPAN_SAMPLES) * SIM_TEMPERATURE_STEP_CENTI_C
        )
        voltage_millivolt = SIM_VOLTAGE_BASE_MV + (
            (index % SIM_VOLTAGE_SPAN_SAMPLES) * SIM_VOLTAGE_STEP_MV
        )
        battery_deci_pct = SIM_CAPACITY_BASE_DECI_PCT - (
            (index % SIM_CAPACITY_SPAN_SAMPLES) * SIM_CAPACITY_DECREMENT_PER_SAMPLE
        )

        return (
            bytes((status_code,))
            + int(temperature_centi_c).to_bytes(2, "big", signed=True)
            + int(voltage_millivolt).to_bytes(2, "big", signed=False)
            + int(battery_deci_pct).to_bytes(2, "big", signed=False)
        )

    def _toggle_auto_simulation(self) -> None:
        if self._auto_sim_running:
            self._stop_auto_simulation()
            self._log("Auto simulation stopped")
            return

        self._auto_sim_running = True
        self.auto_sim_button.configure(text=self._auto_sim_button_text())
        self._log(
            f"Auto simulation started ({self._current_sim_frequency_hz():g} Hz)"
        )
        self._run_auto_simulation_step()

    def _run_auto_simulation_step(self) -> None:
        if not self._auto_sim_running:
            return

        self._inject_simulated_telemetry()
        self._auto_sim_after_id = self.root.after(
            self._current_auto_sim_interval_ms(),
            self._run_auto_simulation_step,
        )

    def _stop_auto_simulation(self) -> None:
        self._auto_sim_running = False
        self.auto_sim_button.configure(text=self._auto_sim_button_text())
        if self._auto_sim_after_id is not None:
            self.root.after_cancel(self._auto_sim_after_id)
            self._auto_sim_after_id = None

    def _toggle_sim_frequency(self) -> None:
        self._sim_frequency_index = (
            self._sim_frequency_index + 1
        ) % len(GUI_SIM_FREQUENCY_OPTIONS_HZ)
        self.sim_frequency_button.configure(text=self._sim_frequency_button_text())
        self.auto_sim_button.configure(text=self._auto_sim_button_text())
        self._log(
            f"Simulation frequency set to {self._current_sim_frequency_hz():g} Hz"
        )

        if self._auto_sim_running:
            if self._auto_sim_after_id is not None:
                self.root.after_cancel(self._auto_sim_after_id)
            self._auto_sim_after_id = self.root.after(
                self._current_auto_sim_interval_ms(),
                self._run_auto_simulation_step,
            )

    def _sim_frequency_button_text(self) -> str:
        return f"Simulation Rate: {self._current_sim_frequency_hz():g} Hz"

    def _auto_sim_button_text(self) -> str:
        action = "Stop" if self._auto_sim_running else "Start"
        return f"{action} Auto Simulation ({self._current_sim_frequency_hz():g} Hz)"

    def _current_sim_frequency_hz(self) -> float:
        return float(GUI_SIM_FREQUENCY_OPTIONS_HZ[self._sim_frequency_index])

    def _current_auto_sim_interval_ms(self) -> int:
        frequency_hz = self._current_sim_frequency_hz()
        if frequency_hz <= 0:
            raise ValueError("Simulation frequency must be positive")
        return max(1, int(round(1000.0 / frequency_hz)))

    def _start_rx_thread(self) -> None:
        self._rx_thread = threading.Thread(target=self._rx_loop, daemon=True)
        self._rx_thread.start()

    def _rx_loop(self) -> None:
        while not self._rx_stop_event.is_set():
            serial_port = self._serial_port
            if serial_port is None:
                time.sleep(GUI_RX_POLL_INTERVAL_S)
                continue

            try:
                decoded_packets = self._receiver.process_serial_once(
                    serial_port,
                    max_read_size=EGSE_SERIAL_MAX_READ_SIZE,
                )
                for decoded in decoded_packets:
                    self._rx_queue.put(decoded)
            except (OSError, SerialException):
                self._rx_queue.put(None)
                time.sleep(GUI_RX_POLL_INTERVAL_S)

            time.sleep(GUI_RX_POLL_INTERVAL_S)

    def _process_rx_queue(self) -> None:
        try:
            while True:
                item = self._rx_queue.get_nowait()
                if item is None:
                    self._disconnect()
                    self._log("RX error, disconnected")
                    break
                self._handle_decoded_packet(item)
        except queue.Empty:
            pass

        self.root.after(GUI_UPDATE_INTERVAL_MS, self._process_rx_queue)

    def _handle_decoded_packet(self, decoded_packet) -> None:
        packet = decoded_packet.space_packet
        if packet.packet_type != PacketType.TELEMETRY:
            return

        try:
            telemetry_apid = int(self.tm_apid_var.get(), 0)
        except ValueError:
            telemetry_apid = CCSDS_DEFAULT_TM_APID

        if packet.apid != telemetry_apid:
            return

        try:
            sample = decode_telemetry_payload(packet.data_field)
        except (TypeError, ValueError):
            self._log("Ignored telemetry packet with unsupported payload format")
            return

        self._sample_index += 1
        self._x.append(self._sample_index)
        self._temperature.append(sample.temperature_c)
        self._voltage.append(sample.voltage_v)
        self._capacity.append(sample.battery_capacity_pct)

        self.state_status_var.set(
            f"Status: {sample.status_text} (code {sample.status_code})"
        )
        self.state_temp_var.set(f"Temperature: {sample.temperature_c:.2f} °C")
        self.state_voltage_var.set(f"Voltage: {sample.voltage_v:.3f} V")
        self.state_capacity_var.set(
            f"Battery Capacity: {sample.battery_capacity_pct:.1f} %"
        )
        self.state_update_var.set(
            f"Last Update: {sample.timestamp.strftime('%H:%M:%S')}"
        )

        self._refresh_plots()

    def _refresh_plots(self) -> None:
        x = list(self._x)
        self.temp_line.set_data(x, list(self._temperature))
        self.voltage_line.set_data(x, list(self._voltage))
        self.capacity_line.set_data(x, list(self._capacity))

        for axis in (self.ax_temp, self.ax_voltage, self.ax_capacity):
            axis.relim()
            axis.autoscale_view()

        self.canvas.draw_idle()

    def _clear_telemetry_data(self) -> None:
        self._x.clear()
        self._temperature.clear()
        self._voltage.clear()
        self._capacity.clear()
        self._sample_index = 0

        self.state_status_var.set("Status: -")
        self.state_temp_var.set("Temperature: -")
        self.state_voltage_var.set("Voltage: -")
        self.state_capacity_var.set("Battery Capacity: -")
        self.state_update_var.set("Last Update: -")

        self._refresh_plots()
        self._log("Telemetry data cleared")

    def _log(self, text: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[{timestamp}] {text}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _on_close(self) -> None:
        self._stop_auto_simulation()
        self._rx_stop_event.set()
        self._disconnect()
        self.root.destroy()


def main() -> None:
    if not TK_AVAILABLE:
        raise SystemExit(
            "tkinter is not available. Install python3-tk (Linux) and retry."
        )
    if not MATPLOTLIB_AVAILABLE:
        raise SystemExit(
            "matplotlib is not available. Install GUI extras: pip install -e .[gui]"
        )

    root = tk.Tk()
    EgseGuiApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
