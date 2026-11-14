import sys
import time
import math
import random
import csv
from datetime import datetime
from collections import deque
import threading

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import serial
import serial.tools.list_ports

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk


class SerialScopeApp:
    """
    SerialScope Pro: Interactive UART Telemetry, Real-Time DSP Filter,
    and Bi-Directional Hardware Control Studio for Embedded Systems.
    """

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("SerialScope Pro — Interactive Telemetry, DSP & Hardware Control Studio")
        self.root.geometry("1260x780")
        self.root.minsize(1100, 700)
        self.root.configure(bg="#181825")

        # Connection & Thread State
        self.is_connected = False
        self.is_paused = False
        self.is_simulation = False
        self.serial_port = None
        self.read_thread = None

        # Data Buffers
        self.max_points = 250
        self.time_window = deque(maxlen=self.max_points)
        self.ch1_raw_window = deque(maxlen=self.max_points)
        self.ch1_filt_window = deque(maxlen=self.max_points)
        self.ch2_window = deque(maxlen=self.max_points)

        # Full History for CSV Export
        self.recorded_data = []
        self.start_time = None

        # Real-time DSP & Threshold State
        self.ema_alpha = 0.25  # Low-pass filter smoothing factor
        self.last_filtered_val = None
        self.threshold_val = 30.0
        self.threshold_enabled = tk.BooleanVar(value=True)
        self.show_raw_signal = tk.BooleanVar(value=True)
        self.show_ch2_signal = tk.BooleanVar(value=True)
        self.alarm_triggered = False

        # Interactive Simulation / Control Parameters (Changed via Sliders)
        self.sim_setpoint = 25.0
        self.sim_amplitude = 5.0
        self.sim_noise = 1.2

        # Statistics
        self.ch1_min = None
        self.ch1_max = None
        self.ch1_sum = 0.0
        self.sample_count = 0

        self._setup_styles()
        self._build_ui()
        self._refresh_ports()

        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)
        self._update_plot_loop()

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure("TFrame", background="#181825")
        style.configure("Card.TFrame", background="#1e1e2e", relief="flat")
        style.configure(
            "TLabel",
            background="#1e1e2e",
            foreground="#cdd6f4",
            font=("Segoe UI", 9)
        )
        style.configure(
            "Header.TLabel",
            background="#181825",
            foreground="#89b4fa",
            font=("Segoe UI", 14, "bold")
        )
        style.configure(
            "Section.TLabel",
            background="#1e1e2e",
            foreground="#cba6f7",
            font=("Segoe UI", 9, "bold")
        )
        style.configure(
            "StatValue.TLabel",
            background="#1e1e2e",
            foreground="#a6e3a1",
            font=("Consolas", 11, "bold")
        )
        style.configure(
            "TCheckbutton",
            background="#1e1e2e",
            foreground="#cdd6f4",
            font=("Segoe UI", 9)
        )
        style.map("TCheckbutton", background=[("active", "#1e1e2e")])

        style.configure("TButton", font=("Segoe UI", 9, "bold"), padding=5)
        style.configure("Connect.TButton", background="#a6e3a1", foreground="#11111b")
        style.map("Connect.TButton", background=[("active", "#b8f2b4")])

        style.configure("Disconnect.TButton", background="#f38ba8", foreground="#11111b")
        style.map("Disconnect.TButton", background=[("active", "#f5a3ba")])

        style.configure("Action.TButton", background="#313244", foreground="#cdd6f4")
        style.map("Action.TButton", background=[("active", "#45475a")])

        style.configure("Accent.TButton", background="#89b4fa", foreground="#11111b")
        style.map("Accent.TButton", background=[("active", "#b4befe")])

    def _build_ui(self):
        # Top Header Bar
        header_frame = ttk.Frame(self.root)
        header_frame.pack(fill=tk.X, padx=14, pady=(10, 4))

        ttk.Label(
            header_frame,
            text="⚡ SerialScope Pro | Interactive Telemetry, DSP Filter & Hardware Control",
            style="Header.TLabel"
        ).pack(side=tk.LEFT)

        self.alarm_lbl = ttk.Label(
            header_frame,
            text="● THRESHOLD OK",
            foreground="#a6e3a1",
            background="#181825",
            font=("Consolas", 10, "bold")
        )
        self.alarm_lbl.pack(side=tk.RIGHT, padx=(15, 0))

        self.status_lbl = ttk.Label(
            header_frame,
            text="● DISCONNECTED",
            foreground="#f38ba8",
            background="#181825",
            font=("Consolas", 10, "bold")
        )
        self.status_lbl.pack(side=tk.RIGHT)

        # Main 3-Column Layout (Left: Connection & DSP, Center: Plot & Toolbar, Right: Interactive TX Control)
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=14, pady=6)

        # ==================== LEFT PANEL: CONNECTION, DSP & STATS ====================
        left_panel = ttk.Frame(main_frame, style="Card.TFrame", width=280)
        left_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        left_panel.pack_propagate(False)

        # 1. Connection Section
        conn_box = ttk.Frame(left_panel, style="Card.TFrame")
        conn_box.pack(fill=tk.X, padx=12, pady=10)

        ttk.Label(conn_box, text="1. UART / DEVICE CONNECTION", style="Section.TLabel").pack(anchor=tk.W, pady=(0, 6))
        ttk.Label(conn_box, text="Target Port:").pack(anchor=tk.W)

        port_row = ttk.Frame(conn_box, style="Card.TFrame")
        port_row.pack(fill=tk.X, pady=(2, 8))

        self.port_combo = ttk.Combobox(port_row, state="readonly", font=("Segoe UI", 9))
        self.port_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))

        ttk.Button(port_row, text="↻", width=3, style="Action.TButton", command=self._refresh_ports).pack(side=tk.RIGHT)

        ttk.Label(conn_box, text="Baud Rate:").pack(anchor=tk.W)
        self.baud_combo = ttk.Combobox(
            conn_box,
            values=["9600", "19200", "38400", "57600", "115200", "230400"],
            state="readonly",
            font=("Segoe UI", 9)
        )
        self.baud_combo.set("115200")
        self.baud_combo.pack(fill=tk.X, pady=(2, 10))

        self.connect_btn = ttk.Button(
            conn_box,
            text="▶ CONNECT & STREAM",
            style="Connect.TButton",
            command=self._toggle_connection
        )
        self.connect_btn.pack(fill=tk.X, pady=(0, 5))

        self.pause_btn = ttk.Button(
            conn_box,
            text="⏸ Pause Oscilloscope",
            style="Action.TButton",
            command=self._toggle_pause,
            state=tk.DISABLED
        )
        self.pause_btn.pack(fill=tk.X)

        tk.Frame(left_panel, bg="#313244", height=1).pack(fill=tk.X, padx=12, pady=4)

        # 2. Real-Time DSP & Signal Conditioning Section
        dsp_box = ttk.Frame(left_panel, style="Card.TFrame")
        dsp_box.pack(fill=tk.X, padx=12, pady=6)

        ttk.Label(dsp_box, text="2. REAL-TIME DSP & TRIGGER", style="Section.TLabel").pack(anchor=tk.W, pady=(0, 6))

        self.lbl_filter_alpha = ttk.Label(dsp_box, text="Low-Pass Filter (EMA α: 0.25):")
        self.lbl_filter_alpha.pack(anchor=tk.W)

        self.alpha_scale = tk.Scale(
            dsp_box, from_=0.02, to=1.0, resolution=0.02, orient=tk.HORIZONTAL,
            bg="#1e1e2e", fg="#cdd6f4", highlightthickness=0, troughcolor="#313244",
            activebackground="#89b4fa", showvalue=False, command=self._on_dsp_change
        )
        self.alpha_scale.set(0.25)
        self.alpha_scale.pack(fill=tk.X, pady=(2, 8))

        self.lbl_thresh = ttk.Label(dsp_box, text="Alarm Threshold Level (30.0):")
        self.lbl_thresh.pack(anchor=tk.W)

        self.thresh_scale = tk.Scale(
            dsp_box, from_=0.0, to=60.0, resolution=0.5, orient=tk.HORIZONTAL,
            bg="#1e1e2e", fg="#cdd6f4", highlightthickness=0, troughcolor="#313244",
            activebackground="#f38ba8", showvalue=False, command=self._on_thresh_change
        )
        self.thresh_scale.set(30.0)
        self.thresh_scale.pack(fill=tk.X, pady=(2, 6))

        ttk.Checkbutton(
            dsp_box, text="Show Raw Noisy Signal (CH1)",
            variable=self.show_raw_signal
        ).pack(anchor=tk.W, pady=1)

        ttk.Checkbutton(
            dsp_box, text="Show Secondary Channel (CH2)",
            variable=self.show_ch2_signal
        ).pack(anchor=tk.W, pady=1)

        ttk.Checkbutton(
            dsp_box, text="Enable Threshold Trigger Line",
            variable=self.threshold_enabled
        ).pack(anchor=tk.W, pady=1)

        tk.Frame(left_panel, bg="#313244", height=1).pack(fill=tk.X, padx=12, pady=4)

        # 3. Live Telemetry Statistics
        stats_box = ttk.Frame(left_panel, style="Card.TFrame")
        stats_box.pack(fill=tk.X, padx=12, pady=6)

        ttk.Label(stats_box, text="3. LIVE METRICS (FILTERED CH1)", style="Section.TLabel").pack(anchor=tk.W, pady=(0, 4))

        self.lbl_current = self._create_stat_row(stats_box, "Current Value:", "0.00")
        self.lbl_min = self._create_stat_row(stats_box, "Minimum:", "0.00")
        self.lbl_max = self._create_stat_row(stats_box, "Maximum:", "0.00")
        self.lbl_avg = self._create_stat_row(stats_box, "Mean (Average):", "0.00")
        self.lbl_count = self._create_stat_row(stats_box, "Samples Logged:", "0")

        # Export & Reset Buttons at Bottom Left
        export_box = ttk.Frame(left_panel, style="Card.TFrame")
        export_box.pack(fill=tk.X, side=tk.BOTTOM, padx=12, pady=10)

        ttk.Button(
            export_box, text="💾 Export Dataset to CSV",
            style="Accent.TButton", command=self._export_csv
        ).pack(fill=tk.X, pady=(0, 5))

        ttk.Button(
            export_box, text="🗑 Clear Buffers & Reset",
            style="Action.TButton", command=self._clear_data
        ).pack(fill=tk.X)

        # ==================== CENTER PANEL: OSCILLOSCOPE & ZOOM TOOLBAR ====================
        center_panel = ttk.Frame(main_frame, style="Card.TFrame")
        center_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        self.fig = Figure(figsize=(6.5, 4.8), dpi=100, facecolor="#1e1e2e")
        self.ax = self.fig.add_subplot(111)
        self._style_axes()

        # Plot Lines: Raw (faint), Filtered (bold green), CH2 (cyan dashed), Threshold (red dotted)
        self.line_raw, = self.ax.plot([], [], color="#9399b2", linewidth=1.0, alpha=0.45, label="CH1 Raw (Noisy)")
        self.line_filt, = self.ax.plot([], [], color="#a6e3a1", linewidth=2.2, label="CH1 DSP Filtered")
        self.line_ch2, = self.ax.plot([], [], color="#89dceb", linewidth=1.6, linestyle="--", label="CH2 Reference")
        self.line_thresh, = self.ax.plot([], [], color="#f38ba8", linewidth=1.3, linestyle=":", label="Alarm Threshold")

        self.ax.legend(loc="upper right", facecolor="#181825", edgecolor="#313244", labelcolor="#cdd6f4", fontsize=8)

        self.canvas = FigureCanvasTkAgg(self.fig, master=center_panel)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 0))

        # Interactive Matplotlib Navigation Toolbar (Zoom, Pan, Save PNG)
        toolbar_frame = tk.Frame(center_panel, bg="#1e1e2e")
        toolbar_frame.pack(fill=tk.X, padx=8, pady=2)
        self.toolbar = NavigationToolbar2Tk(self.canvas, toolbar_frame)
        self.toolbar.config(bg="#1e1e2e")
        for widget in self.toolbar.winfo_children():
            try:
                widget.config(background="#313244")
            except tk.TclError:
                pass
            try:
                widget.config(foreground="#cdd6f4")
            except tk.TclError:
                pass
        self.toolbar.update()

        # ==================== RIGHT PANEL: INTERACTIVE HARDWARE CONTROL (TX) ====================
        right_panel = ttk.Frame(main_frame, style="Card.TFrame", width=310)
        right_panel.pack(side=tk.RIGHT, fill=tk.Y)
        right_panel.pack_propagate(False)

        ctrl_box = ttk.Frame(right_panel, style="Card.TFrame")
        ctrl_box.pack(fill=tk.X, padx=12, pady=10)

        ttk.Label(ctrl_box, text="4. INTERACTIVE HARDWARE TUNING", style="Section.TLabel").pack(anchor=tk.W, pady=(0, 4))
        ttk.Label(
            ctrl_box,
            text="Adjusting sliders sends live UART commands\n(e.g. SET:25.0) & updates simulation in real time:",
            foreground="#a6adc8",
            font=("Segoe UI", 8)
        ).pack(anchor=tk.W, pady=(0, 8))

        # Parameter Slider 1: Setpoint / Offset (or PID Kp)
        self.lbl_param1 = ttk.Label(ctrl_box, text="Target Setpoint / Offset (25.0):")
        self.lbl_param1.pack(anchor=tk.W)
        self.scale_param1 = tk.Scale(
            ctrl_box, from_=5.0, to=45.0, resolution=0.5, orient=tk.HORIZONTAL,
            bg="#1e1e2e", fg="#cdd6f4", highlightthickness=0, troughcolor="#313244",
            activebackground="#a6e3a1", showvalue=False, command=self._on_param1_change
        )
        self.scale_param1.set(25.0)
        self.scale_param1.pack(fill=tk.X, pady=(2, 8))

        # Parameter Slider 2: Gain / Amplitude (or PID Ki / PWM)
        self.lbl_param2 = ttk.Label(ctrl_box, text="Signal Amplitude / PWM Gain (5.0):")
        self.lbl_param2.pack(anchor=tk.W)
        self.scale_param2 = tk.Scale(
            ctrl_box, from_=0.5, to=15.0, resolution=0.5, orient=tk.HORIZONTAL,
            bg="#1e1e2e", fg="#cdd6f4", highlightthickness=0, troughcolor="#313244",
            activebackground="#89b4fa", showvalue=False, command=self._on_param2_change
        )
        self.scale_param2.set(5.0)
        self.scale_param2.pack(fill=tk.X, pady=(2, 8))

        # Parameter Slider 3: Sensor Noise Injection (or PID Kd)
        self.lbl_param3 = ttk.Label(ctrl_box, text="Simulated Sensor Noise (1.2):")
        self.lbl_param3.pack(anchor=tk.W)
        self.scale_param3 = tk.Scale(
            ctrl_box, from_=0.0, to=5.0, resolution=0.1, orient=tk.HORIZONTAL,
            bg="#1e1e2e", fg="#cdd6f4", highlightthickness=0, troughcolor="#313244",
            activebackground="#cba6f7", showvalue=False, command=self._on_param3_change
        )
        self.scale_param3.set(1.2)
        self.scale_param3.pack(fill=tk.X, pady=(2, 10))

        # Quick Macro Buttons for Embedded Testing
        ttk.Label(ctrl_box, text="Quick Hardware Macros (TX):", foreground="#89b4fa", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(4, 4))

        macro_grid = ttk.Frame(ctrl_box, style="Card.TFrame")
        macro_grid.pack(fill=tk.X, pady=(0, 8))

        ttk.Button(macro_grid, text="⚡ Calibrate", style="Action.TButton", command=lambda: self._send_serial_cmd("CMD:CALIBRATE")).grid(row=0, column=0, sticky="ew", padx=(0, 3), pady=2)
        ttk.Button(macro_grid, text="🛑 E-Stop", style="Disconnect.TButton", command=lambda: self._send_serial_cmd("CMD:ESTOP")).grid(row=0, column=1, sticky="ew", padx=(3, 0), pady=2)
        ttk.Button(macro_grid, text="🔄 Step Pulse", style="Action.TButton", command=self._inject_step_response).grid(row=1, column=0, sticky="ew", padx=(0, 3), pady=2)
        ttk.Button(macro_grid, text="📶 Ping MCU", style="Action.TButton", command=lambda: self._send_serial_cmd("CMD:PING")).grid(row=1, column=1, sticky="ew", padx=(3, 0), pady=2)
        macro_grid.columnconfigure(0, weight=1)
        macro_grid.columnconfigure(1, weight=1)

        # Custom Command Entry
        ttk.Label(ctrl_box, text="Send Custom Serial Command (TX):").pack(anchor=tk.W, pady=(4, 2))
        cmd_row = ttk.Frame(ctrl_box, style="Card.TFrame")
        cmd_row.pack(fill=tk.X)

        self.cmd_entry = ttk.Entry(cmd_row, font=("Consolas", 9))
        self.cmd_entry.insert(0, "PID:1.5,0.2,0.05")
        self.cmd_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        self.cmd_entry.bind("<Return>", lambda e: self._send_custom_entry())

        ttk.Button(cmd_row, text="Send", width=6, style="Accent.TButton", command=self._send_custom_entry).pack(side=tk.RIGHT)

        tk.Frame(right_panel, bg="#313244", height=1).pack(fill=tk.X, padx=12, pady=8)

        # 5. Live Bi-Directional UART Terminal Log (RX / TX)
        term_box = ttk.Frame(right_panel, style="Card.TFrame")
        term_box.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 10))

        ttk.Label(term_box, text="5. BI-DIRECTIONAL UART MONITOR", style="Section.TLabel").pack(anchor=tk.W, pady=(0, 4))

        self.term_text = tk.Text(
            term_box, bg="#11111b", fg="#a6e3a1", font=("Consolas", 8),
            height=10, relief="flat", state=tk.DISABLED
        )
        self.term_text.pack(fill=tk.BOTH, expand=True)

    def _create_stat_row(self, parent, label_text, default_val):
        row = ttk.Frame(parent, style="Card.TFrame")
        row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text=label_text).pack(side=tk.LEFT)
        val_lbl = ttk.Label(row, text=default_val, style="StatValue.TLabel")
        val_lbl.pack(side=tk.RIGHT)
        return val_lbl

    def _style_axes(self):
        self.ax.set_facecolor("#11111b")
        self.ax.set_title("Real-Time Sensor Telemetry & DSP Filter Output", color="#cdd6f4", fontsize=10, pad=8)
        self.ax.set_xlabel("Elapsed Time (s)", color="#a6adc8", fontsize=9)
        self.ax.set_ylabel("Amplitude / Sensor Value", color="#a6adc8", fontsize=9)
        self.ax.tick_params(colors="#a6adc8", labelsize=8)
        for spine in self.ax.spines.values():
            spine.set_color("#313244")
        self.ax.grid(True, linestyle="--", alpha=0.25, color="#585b70")

    def _log_terminal(self, prefix: str, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-4]
        line = f"[{timestamp}] {prefix}: {message}\n"
        self.term_text.config(state=tk.NORMAL)
        self.term_text.insert(tk.END, line)
        # Keep last 80 lines in terminal
        lines = int(self.term_text.index("end-1c").split(".")[0])
        if lines > 80:
            self.term_text.delete("1.0", "2.0")
        self.term_text.see(tk.END)
        self.term_text.config(state=tk.DISABLED)

    # ==================== INTERACTIVE CALLBACKS ====================
    def _on_dsp_change(self, val):
        self.ema_alpha = float(val)
        self.lbl_filter_alpha.config(text=f"Low-Pass Filter (EMA α: {self.ema_alpha:.2f}):")

    def _on_thresh_change(self, val):
        self.threshold_val = float(val)
        self.lbl_thresh.config(text=f"Alarm Threshold Level ({self.threshold_val:.1f}):")

    def _on_param1_change(self, val):
        self.sim_setpoint = float(val)
        self.lbl_param1.config(text=f"Target Setpoint / Offset ({self.sim_setpoint:.1f}):")
        if self.is_connected:
            self._send_serial_cmd(f"SETPOINT:{self.sim_setpoint:.1f}", quiet=True)

    def _on_param2_change(self, val):
        self.sim_amplitude = float(val)
        self.lbl_param2.config(text=f"Signal Amplitude / PWM Gain ({self.sim_amplitude:.1f}):")
        if self.is_connected:
            self._send_serial_cmd(f"GAIN:{self.sim_amplitude:.1f}", quiet=True)

    def _on_param3_change(self, val):
        self.sim_noise = float(val)
        self.lbl_param3.config(text=f"Simulated Sensor Noise ({self.sim_noise:.1f}):")

    def _inject_step_response(self):
        """Simulates a sudden step disturbance to test filter/PID response."""
        self.sim_setpoint += 10.0
        if self.sim_setpoint > 45.0:
            self.sim_setpoint = 15.0
        self.scale_param1.set(self.sim_setpoint)
        self._send_serial_cmd(f"STEP:{self.sim_setpoint:.1f}")

    def _send_custom_entry(self):
        cmd = self.cmd_entry.get().strip()
        if cmd:
            self._send_serial_cmd(cmd)

    def _send_serial_cmd(self, cmd_str: str, quiet: bool = False):
        if not self.is_connected:
            if not quiet:
                messagebox.showinfo("Not Connected", "Connect to a port or Simulation Mode first to send commands.")
            return

        if not self.is_simulation and self.serial_port and self.serial_port.is_open:
            try:
                self.serial_port.write((cmd_str + "\n").encode("utf-8"))
            except Exception as e:
                self._log_terminal("ERR", str(e))
                return

        if not quiet:
            self._log_terminal("TX -> MCU", cmd_str)

    # ==================== PORT & STREAMING LOGIC ====================
    def _refresh_ports(self):
        ports = serial.tools.list_ports.comports()
        port_list = [f"{p.device} - {p.description}" for p in ports]
        port_list.append("SIMULATION - Interactive Virtual MCU & Sensor")
        self.port_combo["values"] = port_list
        if port_list:
            self.port_combo.current(len(port_list) - 1)  # Default to Simulation for instant testing

    def _toggle_connection(self):
        if not self.is_connected:
            self._start_connection()
        else:
            self._stop_connection()

    def _start_connection(self):
        selected = self.port_combo.get()
        if not selected:
            return

        if self.start_time is None:
            self.start_time = time.time()

        if selected.startswith("SIMULATION"):
            self.is_simulation = True
            self.is_connected = True
            self._update_ui_connected("● SIMULATION ACTIVE", "#89b4fa")
            self._log_terminal("SYS", "Interactive Virtual MCU Started.")
            self.read_thread = threading.Thread(target=self._simulation_worker, daemon=True)
            self.read_thread.start()
        else:
            port_name = selected.split(" - ")[0]
            baud_rate = int(self.baud_combo.get())
            try:
                self.serial_port = serial.Serial(port_name, baud_rate, timeout=1)
                time.sleep(0.4)
                self.serial_port.reset_input_buffer()
                self.is_simulation = False
                self.is_connected = True
                self._update_ui_connected(f"● CONNECTED ({port_name})", "#a6e3a1")
                self._log_terminal("SYS", f"Opened {port_name} @ {baud_rate} bps")
                self.read_thread = threading.Thread(target=self._serial_worker, daemon=True)
                self.read_thread.start()
            except Exception as e:
                messagebox.showerror("Connection Error", f"Could not open serial port:\n{e}")

    def _stop_connection(self):
        self.is_connected = False
        self.is_paused = False
        if self.serial_port and self.serial_port.is_open:
            try:
                self.serial_port.close()
            except Exception:
                pass
        self._update_ui_disconnected()
        self._log_terminal("SYS", "Stream stopped.")

    def _update_ui_connected(self, status_text, color):
        self.status_lbl.config(text=status_text, foreground=color)
        self.connect_btn.config(text="⏹ DISCONNECT", style="Disconnect.TButton")
        self.pause_btn.config(state=tk.NORMAL, text="⏸ Pause Oscilloscope")
        self.port_combo.config(state="disabled")
        self.baud_combo.config(state="disabled")

    def _update_ui_disconnected(self):
        self.status_lbl.config(text="● DISCONNECTED", foreground="#f38ba8")
        self.connect_btn.config(text="▶ CONNECT & STREAM", style="Connect.TButton")
        self.pause_btn.config(state=tk.DISABLED, text="⏸ Pause Oscilloscope")
        self.port_combo.config(state="readonly")
        self.baud_combo.config(state="readonly")

    def _toggle_pause(self):
        self.is_paused = not self.is_paused
        if self.is_paused:
            self.pause_btn.config(text="▶ Resume Oscilloscope")
        else:
            self.pause_btn.config(text="⏸ Pause Oscilloscope")

    def _parse_and_store(self, raw_line: str):
        if not raw_line:
            return

        cleaned = raw_line.replace(";", ",").replace(" ", ",")
        parts = [p.strip() for p in cleaned.split(",") if p.strip()]

        values = []
        for part in parts:
            if ":" in part:
                part = part.split(":")[-1].strip()
            try:
                values.append(float(part))
            except ValueError:
                continue

        if not values:
            return

        raw_val1 = values[0]
        val2 = values[1] if len(values) > 1 else 0.0

        # Real-Time Exponential Moving Average (Low-Pass DSP Filter)
        if self.last_filtered_val is None:
            filt_val1 = raw_val1
        else:
            filt_val1 = (self.ema_alpha * raw_val1) + ((1.0 - self.ema_alpha) * self.last_filtered_val)
        self.last_filtered_val = filt_val1

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        elapsed = round(time.time() - self.start_time, 2)

        self.recorded_data.append([now_str, elapsed, round(raw_val1, 3), round(filt_val1, 3), round(val2, 3)])

        self.sample_count += 1
        self.ch1_sum += filt_val1
        if self.ch1_min is None or filt_val1 < self.ch1_min:
            self.ch1_min = filt_val1
        if self.ch1_max is None or filt_val1 > self.ch1_max:
            self.ch1_max = filt_val1

        # Threshold Check
        self.alarm_triggered = filt_val1 >= self.threshold_val

        if not self.is_paused:
            self.time_window.append(elapsed)
            self.ch1_raw_window.append(raw_val1)
            self.ch1_filt_window.append(filt_val1)
            self.ch2_window.append(val2)

        # Log every 15th packet to terminal so it stays readable
        if self.sample_count % 15 == 0:
            self.root.after(0, self._log_terminal, "RX <- MCU", f"Raw:{raw_val1:.2f} | Filt:{filt_val1:.2f} | CH2:{val2:.2f}")

    def _serial_worker(self):
        while self.is_connected and self.serial_port and self.serial_port.is_open:
            try:
                if self.serial_port.in_waiting > 0:
                    line = self.serial_port.readline().decode("utf-8", errors="ignore").strip()
                    self._parse_and_store(line)
                else:
                    time.sleep(0.01)
            except Exception:
                break

    def _simulation_worker(self):
        t = 0.0
        while self.is_connected and self.is_simulation:
            # Interactive Signal: responds immediately to Right-Panel Sliders!
            noise = random.uniform(-self.sim_noise, self.sim_noise)
            ch1_raw = self.sim_setpoint + self.sim_amplitude * math.sin(t) + noise
            ch2_ref = self.sim_setpoint + (self.sim_amplitude * 0.6) * math.cos(t * 0.7)

            fake_serial_line = f"{ch1_raw:.2f},{ch2_ref:.2f}"
            self._parse_and_store(fake_serial_line)

            t += 0.14
            time.sleep(0.06)

    def _update_plot_loop(self):
        if self.is_connected and not self.is_paused and len(self.time_window) > 1:
            t_list = list(self.time_window)
            raw_list = list(self.ch1_raw_window)
            filt_list = list(self.ch1_filt_window)
            ch2_list = list(self.ch2_window)

            # Toggle visibility based on user checkboxes
            self.line_raw.set_data(t_list, raw_list if self.show_raw_signal.get() else [])
            self.line_filt.set_data(t_list, filt_list)
            self.line_ch2.set_data(t_list, ch2_list if self.show_ch2_signal.get() else [])

            if self.threshold_enabled.get():
                self.line_thresh.set_data([t_list[0], t_list[-1]], [self.threshold_val, self.threshold_val])
            else:
                self.line_thresh.set_data([], [])

            self.ax.set_xlim(min(t_list), max(t_list) + 0.5)

            active_y = list(filt_list)
            if self.show_raw_signal.get():
                active_y.extend(raw_list)
            if self.show_ch2_signal.get():
                active_y.extend(ch2_list)
            if self.threshold_enabled.get():
                active_y.append(self.threshold_val)

            min_y, max_y = min(active_y), max(active_y)
            margin = (max_y - min_y) * 0.15 if max_y != min_y else 2.0
            self.ax.set_ylim(min_y - margin, max_y + margin)

            self.canvas.draw_idle()

            # Update Stats & Alarm Indicator
            current_val = filt_list[-1]
            avg_val = self.ch1_sum / self.sample_count if self.sample_count > 0 else 0.0

            self.lbl_current.config(text=f"{current_val:.2f}")
            self.lbl_min.config(text=f"{self.ch1_min:.2f}")
            self.lbl_max.config(text=f"{self.ch1_max:.2f}")
            self.lbl_avg.config(text=f"{avg_val:.2f}")
            self.lbl_count.config(text=f"{self.sample_count}")

            if self.threshold_enabled.get() and self.alarm_triggered:
                self.alarm_lbl.config(text=f"⚠ ALARM: ABOVE {self.threshold_val:.1f}!", foreground="#f38ba8")
            else:
                self.alarm_lbl.config(text="● THRESHOLD OK", foreground="#a6e3a1")

        self.root.after(65, self._update_plot_loop)

    def _export_csv(self):
        if not self.recorded_data:
            messagebox.showinfo("No Data", "No telemetry data recorded yet.")
            return

        default_name = f"telemetry_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        filepath = filedialog.asksaveasfilename(
            title="Export Telemetry to CSV",
            defaultextension=".csv",
            initialfile=default_name,
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")]
        )

        if not filepath:
            return

        try:
            with open(filepath, mode="w", newline="", encoding="utf-8") as file:
                writer = csv.writer(file)
                writer.writerow(["Timestamp", "Elapsed_s", "CH1_Raw", "CH1_DSP_Filtered", "CH2_Value"])
                writer.writerows(self.recorded_data)
            messagebox.showinfo(
                "Export Complete",
                f"Successfully exported {len(self.recorded_data)} samples (Raw + DSP Filtered) to:\n{filepath}"
            )
        except Exception as e:
            messagebox.showerror("Export Error", f"Failed to save CSV:\n{e}")

    def _clear_data(self):
        self.time_window.clear()
        self.ch1_raw_window.clear()
        self.ch1_filt_window.clear()
        self.ch2_window.clear()
        self.recorded_data.clear()

        self.start_time = time.time() if self.is_connected else None
        self.last_filtered_val = None
        self.ch1_min = None
        self.ch1_max = None
        self.ch1_sum = 0.0
        self.sample_count = 0

        self.line_raw.set_data([], [])
        self.line_filt.set_data([], [])
        self.line_ch2.set_data([], [])
        self.line_thresh.set_data([], [])
        self.canvas.draw_idle()

        self.lbl_current.config(text="0.00")
        self.lbl_min.config(text="0.00")
        self.lbl_max.config(text="0.00")
        self.lbl_avg.config(text="0.00")
        self.lbl_count.config(text="0")
        self._log_terminal("SYS", "Buffers cleared.")

    def _on_closing(self):
        self._stop_connection()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = SerialScopeApp(root)
    root.mainloop()