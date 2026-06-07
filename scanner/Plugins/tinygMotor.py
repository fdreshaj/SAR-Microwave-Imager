# GCode motion controller plugin for TinyG — 4-motor tandem configuration
#
# Motor layout (physical: 2 -- 3 -- 1 -- 4):
#   Motor 1 → X  (X1)
#   Motor 2 → Y  (Y1)
#   Motor 3 → A  (X2 tandem — mirrors X)
#   Motor 4 → B  (Y2 tandem — mirrors Y)
#
#   Both X motors (X + A) are commanded together in every X move.
#   Both Y motors (Y + B) are commanded together in every Y move.
#
# Homing strategy — NO LIMIT SWITCHES:
#   G28.3 X0 Y0 A0 B0  — zeros all four axes at the current position.
#   No physical movement occurs.  is_homed is set True immediately.
#
# Key TinyG communication notes:
#   - TinyG does NOT reliably echo 'ok' — never block waiting for it.
#   - Motion completion is detected via JSON status reports {"sr":{"stat":N}}
#     stat 5=run, 8=cycle → still moving; anything else → idle.
#   - Active polling uses {"sr":null} JSON query.
#   - Emergency stop: '!' (feedhold) + '%' (queue flush).

from scanner.motion_controller import MotionControllerPlugin
from scanner.plugin_setting import PluginSettingString, PluginSettingFloat
import serial
from serial.tools import list_ports
import time
import json
import threading
import queue

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextEdit,
    QLineEdit, QPushButton, QLabel, QFrame,
)
from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtGui import QColor, QTextCharFormat, QFont, QTextCursor


# ── TinyG stat constants ────────────────────────────────────────────────────
TINYG_STAT_INIT         = 0
TINYG_STAT_READY        = 1
TINYG_STAT_ALARM        = 2
TINYG_STAT_PROGRAM_STOP = 3
TINYG_STAT_PROGRAM_END  = 4
TINYG_STAT_RUN          = 5
TINYG_STAT_HOLD         = 6
TINYG_STAT_PROBE        = 7
TINYG_STAT_CYCLE        = 8
TINYG_STAT_HOMING       = 9

# Stats that mean motion is still in progress
TINYG_MOVING_STATS = {TINYG_STAT_RUN, TINYG_STAT_CYCLE, TINYG_STAT_HOMING, TINYG_STAT_PROBE}

# ── Logical axis indices (as used by the scanner framework) ─────────────────
AXIS_X = 0   # X1 + X2 tandem  (TinyG X + A)
AXIS_Y = 1   # Y1 + Y2 tandem  (TinyG Y + B)


class _TinyGSignals(QObject):
    rx_line = Signal(str)   # emitted from the reader thread → received by the dialog on the Qt thread


class TinyGTerminalDialog(QDialog):
    """Putty-style serial terminal for live TinyG debugging."""

    QUICK = [
        ("stat",   '{"sr":null}'),
        ("motor1", '{"1":null}'),
        ("motor2", '{"2":null}'),
        ("motor3", '{"3":null}'),
        ("motor4", '{"4":null}'),
        ("A axis", '{"a":null}'),
        ("B axis", '{"b":null}'),
        ("X axis", '{"x":null}'),
        ("Y axis", '{"y":null}'),
        ("hold",   "!"),
        ("flush",  "%"),
        ("home",   "G28.3 X0 Y0 A0 B0"),
    ]

    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self._plugin = plugin
        self._signals = _TinyGSignals()
        self._signals.rx_line.connect(self._append_rx)
        self._history: list[str] = []
        self._hist_idx: int = -1
        self._reader_running = False

        self.setWindowTitle("TinyG Serial Terminal")
        self.resize(860, 560)
        self.setStyleSheet("background:#1e1e1e; color:#d4d4d4;")

        root = QVBoxLayout(self)
        root.setSpacing(4)
        root.setContentsMargins(6, 6, 6, 6)

        # ── output pane ──────────────────────────────────────────────────
        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setFont(QFont("Courier New", 9))
        self._output.setStyleSheet(
            "background:#1e1e1e; color:#d4d4d4; border:1px solid #333;"
        )
        self._output.document().setMaximumBlockCount(1000)
        root.addWidget(self._output, stretch=1)

        # ── quick-send buttons ───────────────────────────────────────────
        btn_frame = QFrame()
        btn_frame.setStyleSheet("background:#252525; border:1px solid #333; border-radius:3px;")
        btn_layout = QHBoxLayout(btn_frame)
        btn_layout.setSpacing(3)
        btn_layout.setContentsMargins(4, 3, 4, 3)
        for label, cmd in self.QUICK:
            b = QPushButton(label)
            b.setFixedHeight(22)
            b.setFont(QFont("Courier New", 8))
            b.setStyleSheet(
                "QPushButton{background:#2d2d2d;color:#9cdcfe;border:1px solid #444;border-radius:2px;padding:0 4px;}"
                "QPushButton:hover{background:#3a3a3a;border-color:#6caddc;}"
                "QPushButton:pressed{background:#1a1a1a;}"
            )
            b.clicked.connect(lambda _=False, c=cmd: self._send(c))
            btn_layout.addWidget(b)
        btn_layout.addStretch()
        root.addWidget(btn_frame)

        # ── TX input row ─────────────────────────────────────────────────
        row = QHBoxLayout()
        row.setSpacing(4)
        lbl = QLabel("TX:")
        lbl.setFont(QFont("Courier New", 9))
        lbl.setStyleSheet("color:#888;")
        self._input = QLineEdit()
        self._input.setFont(QFont("Courier New", 9))
        self._input.setStyleSheet(
            "background:#252525; color:#dcdcaa; border:1px solid #444;"
            "border-radius:2px; padding:1px 4px;"
        )
        self._input.setPlaceholderText("Type GCode or JSON and press Enter…")
        self._input.returnPressed.connect(self._on_enter)
        self._input.installEventFilter(self)

        send_btn = QPushButton("Send")
        send_btn.setFixedWidth(56)
        send_btn.setFont(QFont("Courier New", 9))
        send_btn.setStyleSheet(
            "QPushButton{background:#2d2d2d;color:#4ec9b0;border:1px solid #444;border-radius:2px;}"
            "QPushButton:hover{background:#3a3a3a;}"
        )
        send_btn.clicked.connect(self._on_enter)

        clr_btn = QPushButton("Clear")
        clr_btn.setFixedWidth(56)
        clr_btn.setFont(QFont("Courier New", 9))
        clr_btn.setStyleSheet(send_btn.styleSheet())
        clr_btn.clicked.connect(self._output.clear)

        row.addWidget(lbl)
        row.addWidget(self._input, stretch=1)
        row.addWidget(send_btn)
        row.addWidget(clr_btn)
        root.addLayout(row)

    # ── reader thread lifecycle ───────────────────────────────────────────

    def start_reader(self):
        """Start the background thread that forwards lines from the plugin's rx_queue."""
        if self._reader_running:
            return
        self._reader_running = True
        threading.Thread(target=self._read_loop, daemon=True).start()

    def stop_reader(self):
        self._reader_running = False

    def _read_loop(self):
        """Pull lines from the shared rx_queue and emit them to the UI."""
        while self._reader_running:
            try:
                line = self._plugin.rx_queue.get(timeout=0.1)
                self._signals.rx_line.emit(line)
            except queue.Empty:
                continue

    # ── output helpers ────────────────────────────────────────────────────

    def _append_rx(self, line: str):
        cur = self._output.textCursor()
        cur.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        if '"stat"' in line or '"sr"' in line:
            fmt.setForeground(QColor("#4ec9b0"))   # teal   — status
        elif '"er"' in line or "error" in line.lower():
            fmt.setForeground(QColor("#f44747"))   # red    — error
        elif line.startswith("{"):
            fmt.setForeground(QColor("#9cdcfe"))   # blue   — other JSON
        else:
            fmt.setForeground(QColor("#d4d4d4"))   # white  — plain text
        cur.insertText(f"← {line}\n", fmt)
        self._output.setTextCursor(cur)
        self._output.ensureCursorVisible()

    def _append_tx(self, line: str):
        cur = self._output.textCursor()
        cur.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor("#dcdcaa"))       # yellow — TX
        cur.insertText(f"→ {line}\n", fmt)
        self._output.setTextCursor(cur)
        self._output.ensureCursorVisible()

    # ── send ──────────────────────────────────────────────────────────────

    def _send(self, cmd: str):
        ser = self._plugin.serial_port
        if not ser or not ser.is_open:
            self._append_rx("[not connected — call connect() first]")
            return
        try:
            ser.write((cmd.strip() + "\n").encode("utf-8"))
            ser.flush()
            self._append_tx(cmd.strip())
        except Exception as e:
            self._append_rx(f"[send error: {e}]")

    def _on_enter(self):
        cmd = self._input.text().strip()
        if not cmd:
            return
        self._history.append(cmd)
        self._hist_idx = -1
        self._input.clear()
        self._send(cmd)

    # ── keyboard history navigation ───────────────────────────────────────

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if obj is self._input and event.type() == QEvent.KeyPress:
            key = event.key()
            if key == Qt.Key_Up and self._history:
                if self._hist_idx == -1:
                    self._hist_idx = len(self._history) - 1
                elif self._hist_idx > 0:
                    self._hist_idx -= 1
                self._input.setText(self._history[self._hist_idx])
                return True
            if key == Qt.Key_Down and self._history:
                self._hist_idx += 1
                if self._hist_idx >= len(self._history):
                    self._hist_idx = -1
                    self._input.clear()
                else:
                    self._input.setText(self._history[self._hist_idx])
                return True
        return super().eventFilter(obj, event)

    def closeEvent(self, event):
        self.stop_reader()
        super().closeEvent(event)


class motion_controller_plugin(MotionControllerPlugin):
    def __init__(self):
        super().__init__()

        # ── Scanner type (used for boundary limits) ───────────────────────
        self.scanner_type = PluginSettingString(
            "Scanner Type",
            "N-d Scanner",
            select_options=["Big Scanner", "N-d Scanner"],
            restrict_selections=True
        )
        self.add_setting_pre_connect(self.scanner_type)

        # ── Software position tracking (X, Y — 2D gantry) ────────────────
        self.current_position = [0.0, 0.0]   # [X, Y]
        self.is_homed = False

        # ── Boundary limits — populated in connect() ──────────────────────
        self.x_min = 0.0
        self.x_max = 0.0
        self.y_min = 0.0
        self.y_max = 0.0

        # ── Serial state ──────────────────────────────────────────────────
        self.serial_port: serial.Serial | None = None
        self.resource_name: str | None = None

        # ── Motion state ──────────────────────────────────────────────────
        self._last_stat: int | None = None
        self._move_timeout = 120.0   # seconds

        # ── Shared RX queue — one thread owns the port, everything else ──
        # reads from here so there are no competing ser.read() calls.
        self.rx_queue: queue.Queue[str] = queue.Queue()
        self._port_reader_running = False

        # ── Serial terminal (built once on the Qt thread) ─────────────────
        self._terminal = TinyGTerminalDialog(self)

    # ── Connection ────────────────────────────────────────────────────────────

    def connect(self):
        """
        Open the TinyG serial port.

        Detection order:
          1. Try each COM port; send M115 and wait 1 s for a TinyG identity.
          2. If no port identifies itself, fall back to the first port that
             opened successfully (mirrors the BigTreeTech plugin approach).
        After connecting:
          - Sets boundary limits from scanner_type.
          - Configures G21 (mm) and G91 (incremental).
          - Does NOT home — call home() explicitly when ready.
        """
        scanner_type_str = self.scanner_type.value
        if scanner_type_str == "Big Scanner":
            self.x_min, self.x_max = 0.0, 600.0
            self.y_min, self.y_max = 0.0, 600.0
            print("Scanner boundaries set: Big Scanner (600×600 mm)")
        else:
            self.x_min, self.x_max = 0.0, 300.0
            self.y_min, self.y_max = 0.0, 300.0
            print("Scanner boundaries set: N-d Scanner (300×300 mm)")

        candidates = list(list_ports.comports())
        if not candidates:
            raise ConnectionError("No serial ports found on system")

        print(f"\nAttempting to connect to TinyG across {len(candidates)} serial port(s)...")
        print("Found the following serial ports:")
        for p in candidates:
            print(f"  - {p.device}  ({p.description})")

        confirmed_port: serial.Serial | None = None
        fallback_port:  serial.Serial | None = None
        fallback_name:  str | None = None

        for port_info in candidates:
            port = port_info.device
            print(f"\n  Trying {port}...")
            try:
                ser = serial.Serial(
                    port=port,
                    baudrate=115200,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    timeout=0.1,
                    write_timeout=2.0,
                )
            except (serial.SerialException, OSError) as e:
                print(f"  ✗ Could not open {port}: {e}")
                continue

            if fallback_port is None:
                fallback_port = ser
                fallback_name = port

            time.sleep(0.05)
            ser.reset_input_buffer()
            ser.write(b"M115\n")
            time.sleep(0.05)
            raw = ser.read(ser.in_waiting or 512)
            response = raw.decode("utf-8", errors="replace")
            print(f"  M115 response: {response[:80].strip()!r}")

            if "tinyg" in response.lower() or "firmware" in response.lower():
                print(f"  ✓ TinyG identity confirmed on {port}")
                confirmed_port = ser
                if fallback_port is not ser:
                    fallback_port.close()
                break
            else:
                print(f"  ✗ No TinyG identity (keeping as fallback)")

        if confirmed_port is not None:
            self.serial_port = confirmed_port
            self.resource_name = confirmed_port.port
        elif fallback_port is not None:
            print(f"\n  No TinyG identity on any port — using fallback: {fallback_name}")
            self.serial_port = fallback_port
            self.resource_name = fallback_name
        else:
            raise ConnectionError(
                "Could not open any serial port. "
                "Check USB connection and driver installation."
            )

        print(f"\n✓ Connected to TinyG on {self.resource_name}")

        time.sleep(0.05)
        self.serial_port.reset_input_buffer()
        self.send_gcode_command("G21")   # millimetres
        self.send_gcode_command("G91")   # incremental positioning

        # ── TinyG axis / motor configuration ─────────────────────────────
        # Force A and B to linear mode so they slave correctly to X and Y.
        # These are JSON config writes, not GCode — TinyG accepts them inline.
        print("Configuring A axis (X2 tandem) as linear...")
        self._send_json_config('{"a":{"am":1,"vm":3000,"fr":3000,"tn":-1,"tm":-1}}')

        print("Configuring B axis (Y2 tandem) as linear...")
        self._send_json_config('{"b":{"am":1,"vm":3000,"fr":3000,"tn":-1,"tm":-1}}')

        # Motor 3 must map to A only, motor 4 to B only — keeps them off X/Y
        print("Mapping motor 3 → A axis (ma:3)...")
        self._send_json_config('{"3":{"ma":3}}')

        print("Mapping motor 4 → B axis (ma:4)...")
        self._send_json_config('{"4":{"ma":4}}')

        # Disable soft limits — Python boundary checks handle this,
        # and TinyG soft limits can falsely trigger mid-scan due to float drift.
        print("Disabling soft limits on all axes...")
        self._send_json_config('{"x":{"tn":-1,"tm":-1}}')
        self._send_json_config('{"y":{"tn":-1,"tm":-1}}')
        self._send_json_config('{"a":{"tn":-1,"tm":-1}}')
        self._send_json_config('{"b":{"tn":-1,"tm":-1}}')
        self._send_json_config('{"2":{"po":1}}')
        self._send_json_config('{"3":{"po":1}}')
        MOTOR_CONFIG = {
            "1": {"tr": 1.0000},
            "2": {"tr": 1.0000},
            "3": {"tr": 1.0000},
            "4": {"tr": 1.0000},
        }

        print("Applying per-motor travel calibration...")
        for motor, cfg in MOTOR_CONFIG.items():
            self._send_json_config(json.dumps({motor: cfg}))
        time.sleep(0.05)
        self._drain_input()

        print("Ready. Call home() to zero all axes at the current position.")
        self._start_port_reader()
        self._terminal.start_reader()

    def disconnect(self):
        self._terminal.stop_reader()
        self._port_reader_running = False
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
            print(f"Connection to {self.resource_name} closed.")
        self.serial_port = None

    # ── MotionControllerPlugin interface ──────────────────────────────────────

    def get_axis_display_names(self) -> tuple[str, ...]:
        return ("X (X1+X2)", "Y (Y1+Y2)")

    def get_axis_units(self) -> tuple[str, ...]:
        return ("mm", "mm")

    def set_velocity(self, velocities: dict[int, float] = None) -> None:
        pass   # velocity set inline with F parameter on each move

    def set_acceleration(self, accels: dict[int, float] = None) -> None:
        pass   # TinyG uses jerk-based planning

    def set_config(self, amps, idle_p, idle_time):
        pass

    # ── Motion commands ───────────────────────────────────────────────────────

    def move_absolute(self, move_dist: dict[int, float]) -> dict[int, float] | None:
        """
        Move each logical axis by a relative delta (incremental mode G91).

        Physical layout: 2 -- 3 -- 1 -- 4
          axis 0 → X gantry: motors 1 + 2  → sends G0 X<delta> Y<delta>
          axis 1 → Y gantry: motors 3 + 4  → sends G0 A<delta> B<delta>

        Boundary check is performed before any motion is issued.
        """
        if not self.is_homed:
            raise RuntimeError(
                "Call home() before moving to establish the coordinate origin."
            )

        # ── boundary pre-check ───────────────────────────────────────────
        # Framework passes deltas in units of 0.01 mm; current_position is
        # stored in those same units. Convert to mm only for the GCode command.
        for axis_idx, delta in move_dist.items():
            new_pos_mm = (self.current_position[axis_idx] + delta) / 100
            if axis_idx == AXIS_X:
                if new_pos_mm < self.x_min or new_pos_mm > self.x_max:
                    raise ValueError(
                        f"LIMIT VIOLATION: X delta {delta/100:+.3f} mm would reach "
                        f"{new_pos_mm:.3f} mm, outside [{self.x_min}, {self.x_max}]"
                    )
            elif axis_idx == AXIS_Y:
                if new_pos_mm < self.y_min or new_pos_mm > self.y_max:
                    raise ValueError(
                        f"LIMIT VIOLATION: Y delta {delta/100:+.3f} mm would reach "
                        f"{new_pos_mm:.3f} mm, outside [{self.y_min}, {self.y_max}]"
                    )

        # ── execute ──────────────────────────────────────────────────────
        # Physical layout: 2 -- 3 -- 1 -- 4
        #   X rail = motors 1 (X) + 2 (Y) — opposite ends → G0 X<d> Y<d>
        #   Y rail = motors 3 (A) + 4 (B) — opposite ends → G0 A<d> B<d>
        for axis_idx, delta in move_dist.items():
            delta_mm = delta / 100
            if axis_idx == AXIS_X:
                self.send_gcode_command(f"G0 X{delta_mm:.4f} Y{delta_mm:.4f} F3000")
                self._wait_for_idle()
                self.current_position[AXIS_X] += delta_mm * 100

            elif axis_idx == AXIS_Y:
                self.send_gcode_command(f"G0 A{delta_mm:.4f} B{delta_mm:.4f} F3000")
                self._wait_for_idle()
                self.current_position[AXIS_Y] += delta_mm * 100

            else:
                print(f"Warning: unknown axis index {axis_idx}, skipping.")

        print(
            f"Position: X={self.current_position[AXIS_X]:.2f} mm  "
            f"Y={self.current_position[AXIS_Y]:.2f} mm"
        )
        return {i: self.current_position[i] for i in range(2)}

    def move_relative(self, move_pos: dict[int, float]) -> dict[int, float] | None:
        pass

    def get_current_positions(self) -> tuple[float, ...]:
        return tuple(self.current_position)

    def get_endstop_minimums(self) -> tuple[float, ...]:
        return (self.x_min, self.y_min)

    def get_endstop_maximums(self) -> tuple[float, ...]:
        return (self.x_max, self.y_max)

    def is_moving(self, axis=None) -> list[bool]:
        """All four motors share TinyG's single motion state."""
        stat = self._query_stat()
        moving = stat in TINYG_MOVING_STATS
        return [moving, moving]

    def emergency_stop(self):
        """Feedhold (!) + queue flush (%) — TinyG's immediate stop sequence."""
        print("EMERGENCY STOP — sending feedhold + queue flush.")
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.write(b"!")
            time.sleep(0.05)
            self.serial_port.write(b"%")
            time.sleep(0.05)
            self.send_gcode_command("M112")
        print("Emergency stop sent. Verify machine state before resuming.")

    def home(self, axes=None):
        """
        Soft-zero all four axes at the current physical position.

        Sends:  G28.3 X0 Y0 A0 B0

        This tells TinyG "wherever these axes are right now, call it zero."
        NO MOVEMENT OCCURS — safe to use without limit switches.
        """
        print("Soft homing: zeroing X, Y, A, B at current position (no movement)...")
        self.send_gcode_command("G28.3 X0 Y0 A0 B0")

        time.sleep(0.05)
        self._drain_input()

        self.current_position = [0.0, 0.0]
        self.is_homed = True
        print("✓ All axes zeroed at current position. Ready to scan.")
        return {0: 0.0, 1: 0.0}

    def show_radar(self):
        """Open the TinyG serial terminal dialog."""
        self._terminal.show()
        self._terminal.raise_()

    # ── Serial communication helpers ──────────────────────────────────────────

    def _send_json_config(self, json_str: str) -> str | None:
        """
        Write a TinyG JSON config object and wait for its acknowledgement.

        TinyG config writes return {"r":{...},"f":[1,0,N,checksum]}.
        We block briefly to let TinyG process the write before continuing,
        since sending GCode immediately after a config write can race.
        """
        if not self.serial_port or not self.serial_port.is_open:
            print("Not connected. Call connect() first.")
            return None
        try:
            print(f"→ TinyG cfg: {json_str.strip()}")
            self.serial_port.write((json_str.strip() + "\n").encode("utf-8"))
            self.serial_port.flush()
            # Read up to ~1 s for the config acknowledgement
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                line = self._read_line(timeout=0.2)
                if line:
                    print(f"← TinyG cfg: {line}")
                    if '"f"' in line:   # acknowledgement footer received
                        break
            time.sleep(0.05)            # brief settle after config write
        except serial.SerialException as e:
            print(f"Serial error sending config '{json_str.strip()}': {e}")
        return None

    def send_gcode_command(self, command: str) -> str | None:
        """
        Write a GCode command to TinyG over serial.

        Does NOT wait for 'ok' — TinyG does not reliably send it.
        Returns the first line received within a short window (may be empty).
        Use _wait_for_idle() after motion commands to synchronise.
        """
        if not self.serial_port or not self.serial_port.is_open:
            print("Not connected. Call connect() first.")
            return None
        try:
            print(f"→ TinyG: {command.strip()}")
            self.serial_port.write((command.strip() + "\n").encode("utf-8"))
            self.serial_port.flush()
            line = self._read_line(timeout=0.2)
            if line:
                print(f"← TinyG: {line}")
                self._parse_status_report(line)
            return line
        except serial.SerialException as e:
            print(f"Serial error sending '{command.strip()}': {e}")
            return None

    def _parse_status_report(self, line: str) -> int | None:
        """
        Parse a TinyG JSON status report and cache the stat value.

        Handles:
          {"sr":{"stat":5, "posx":10.0, ...}}
          {"r":{"sr":{"stat":4}}, "f":[1,0,255,0]}
        """
        line = line.strip()
        if not line.startswith("{"):
            return None
        try:
            obj = json.loads(line)
            if "sr" in obj and isinstance(obj["sr"], dict):
                stat = obj["sr"].get("stat")
                if stat is not None:
                    self._last_stat = int(stat)
                    return self._last_stat
            if "r" in obj and isinstance(obj["r"], dict):
                sr = obj["r"].get("sr")
                if isinstance(sr, dict):
                    stat = sr.get("stat")
                    if stat is not None:
                        self._last_stat = int(stat)
                        return self._last_stat
        except (json.JSONDecodeError, KeyError, TypeError):
            pass
        return None

    def _start_port_reader(self):
        """
        Start the single thread that owns ser.read().
        All received lines go into self.rx_queue — nothing else
        should call ser.read() directly.
        """
        if self._port_reader_running:
            return
        self._port_reader_running = True

        def _loop():
            buf = bytearray()
            while self._port_reader_running:
                ser = self.serial_port
                if not ser or not ser.is_open:
                    time.sleep(0.05)
                    continue
                try:
                    b = ser.read(1)
                except Exception:
                    time.sleep(0.05)
                    continue
                if b:
                    if b == b"\n":
                        line = buf.decode("utf-8", errors="replace").strip()
                        buf.clear()
                        if line:
                            self._parse_status_report(line)   # update _last_stat
                            self.rx_queue.put(line)
                    elif b != b"\r":
                        buf.extend(b)
                else:
                    time.sleep(0.005)

        threading.Thread(target=_loop, daemon=True).start()

    def _read_line_from_queue(self, timeout: float = 0.5) -> str:
        """Pull one line from the rx_queue; returns '' on timeout."""
        try:
            return self.rx_queue.get(timeout=timeout)
        except queue.Empty:
            return ""

    def _drain_queue(self):
        """Discard all currently queued lines (used after homing etc.)."""
        while not self.rx_queue.empty():
            try:
                self.rx_queue.get_nowait()
            except queue.Empty:
                break

    def _read_line(self, timeout: float = 0.5) -> str:
        """Compatibility shim — routes to the queue."""
        return self._read_line_from_queue(timeout)

    def _drain_input(self):
        """Drain any pending lines from the queue."""
        self._drain_queue()

    def _query_stat(self) -> int:
        """
        Request a fresh status report with {"sr":null} and return stat.
        Defaults to TINYG_STAT_READY (idle) if no response arrives.
        """
        if not self.serial_port or not self.serial_port.is_open:
            return TINYG_STAT_READY
        try:
            self.serial_port.write(b'{"sr":null}\n')
            self.serial_port.flush()
        except serial.SerialException as e:
            print(f"Serial error querying stat: {e}")
            return TINYG_STAT_READY

        # Wait up to 1 s for a line that contains a stat value
        deadline = time.monotonic() + 0.05
        while time.monotonic() < deadline:
            remaining = max(0.05, deadline - time.monotonic())
            line = self._read_line_from_queue(timeout=remaining)
            if line:
                print(f"← TinyG: {line}")
                stat = self._parse_status_report(line)
                if stat is not None:
                    return stat

        return self._last_stat if self._last_stat is not None else TINYG_STAT_READY

    def _clear_alarm(self) -> bool:
        """
        Attempt to clear a TinyG ALARM state and return True if successful.

        TinyG alarm clear sequence:
          1. Feedhold '!' — stop any residual motion
          2. Queue flush '%' — discard queued moves
          3. {"clear":null} — reset the alarm
          4. Re-send G21 + G91 — restore unit/mode settings
          5. Poll stat until no longer ALARM (up to 2 s)
        """
        if not self.serial_port or not self.serial_port.is_open:
            return False
        try:
            print("  Alarm clear: feedhold + queue flush...")
            self.serial_port.write(b"!")
            time.sleep(0.05)
            self.serial_port.write(b"%")
            time.sleep(0.1)
            print('  Alarm clear: sending {"clear":null}...')
            self.serial_port.write(b'{"clear":null}\n')
            self.serial_port.flush()
            time.sleep(0.2)

            # Restore operating mode
            self.serial_port.write(b"G21\n")
            self.serial_port.flush()
            time.sleep(0.05)
            self.serial_port.write(b"G91\n")
            self.serial_port.flush()
            time.sleep(0.1)

            # Confirm alarm is gone
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                stat = self._query_stat()
                print(f"  Post-clear stat={stat}")
                if stat != TINYG_STAT_ALARM:
                    return True
                time.sleep(0.2)

            return False
        except serial.SerialException as e:
            print(f"Serial error during alarm clear: {e}")
            return False

    def _wait_for_idle(self, timeout: float | None = None) -> bool:
        """
        Block until TinyG is no longer executing motion.

        Consumes lines from rx_queue continuously and polls with
        {"sr":null} every  ms.  Returns True when idle, False on
        timeout.  Raises RuntimeError on ALARM.
        """
        if timeout is None:
            timeout = self._move_timeout
        if not self.serial_port or not self.serial_port.is_open:
            return True

        print("Waiting for motion to complete...")
        deadline  = time.monotonic() + timeout
        last_poll = time.monotonic() - 0.05   # poll immediately on first pass

        while time.monotonic() < deadline:
            # Drain any lines that arrived since the last iteration
            line = self._read_line_from_queue(timeout=0.05)
            if line:
                print(f"← TinyG: {line}")
                # _parse_status_report already called by port reader;
                # call again here so _last_stat is updated on this thread too
                self._parse_status_report(line)

            if time.monotonic() - last_poll >= 0.05:
                stat = self._query_stat()
                last_poll = time.monotonic()
                print(f"  stat={stat}")
                if stat == TINYG_STAT_ALARM:
                    print("WARNING: TinyG ALARM detected — attempting clear and resume.")
                    cleared = self._clear_alarm()
                    if cleared:
                        print("Alarm cleared, resuming wait...")
                        last_poll = time.monotonic()
                        continue
                    else:
                        print("ERROR: Could not clear TinyG alarm. Aborting move.")
                        return False
                if stat not in TINYG_MOVING_STATS:
                    print("Motion complete.")
                    return True

        print(f"WARNING: _wait_for_idle timed out after {timeout:.0f} s")
        return False