import socket
import threading
import os
import time
import re
import math
from datetime import datetime
from scanner.probe_controller import ProbePlugin
from scanner.plugin_setting import PluginSettingString, PluginSettingInteger
from scanner.motion_controller import MotionControllerPlugin
import statistics

# ---------------------------------------------------------------------------
# Matplotlib import — non-blocking interactive backend
# ---------------------------------------------------------------------------
import matplotlib
matplotlib.use('TkAgg')          # works headless-free on most systems;
                                  # fall back to 'Qt5Agg' if TkAgg isn't available
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np


# ===========================================================================
#  Shared scan visualiser
#  Lives here so both plugins can import it without circular deps.
# ===========================================================================
class ScanVisualiser:
    """
    Real-time matplotlib window that updates as scan data streams in.

    Layout
    ------
    Top-left  : polar plot   — filtered ultrasound distance (blue dots)
                               detected objects highlighted in red
    Top-right : distance vs angle line chart  (raw=faint, filtered=solid)
    Bottom    : IR vs angle bar/line chart
    """

    WINDOW_DEFAULT  = 5      # moving-average window
    MAX_DIST_DEFAULT = 150.0  # cm — readings beyond this are clipped
    OBJ_GAP_DEFAULT  = 8      # degrees gap to split objects

    def __init__(self):
        self._lock = threading.Lock()

        # --- tunable parameters (can be updated live) ---
        self.window_size = self.WINDOW_DEFAULT
        self.max_dist    = self.MAX_DIST_DEFAULT
        self.obj_gap_deg = self.OBJ_GAP_DEFAULT

        # --- raw data buffers ---
        self._angles:  list[float] = []
        self._us_raw:  list[float] = []
        self._ir_raw:  list[float] = []

        # --- detected objects (populated after each update) ---
        self.objects: list[dict] = []

        # --- figure handles ---
        self._fig      = None
        self._ax_polar = None
        self._ax_dist  = None
        self._ax_ir    = None
        self._running  = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self):
        """Open the matplotlib window (non-blocking — runs in its own thread)."""
        if self._running:
            return
        self._running = True
        t = threading.Thread(target=self._build_figure, daemon=True)
        t.start()

    def stop(self):
        self._running = False
        if self._fig:
            try:
                plt.close(self._fig)
            except Exception:
                pass

    def reset(self):
        with self._lock:
            self._angles.clear()
            self._us_raw.clear()
            self._ir_raw.clear()
            self.objects.clear()

    def add_point(self, angle: float, us_cm: float, ir_raw: float):
        """
        Feed one scan reading.  Thread-safe.
        Clamps ultrasound to max_dist so noisy outliers don't break the axes.
        """
        with self._lock:
            self._angles.append(float(angle))
            self._us_raw.append(min(float(us_cm), self.max_dist * 1.05))
            self._ir_raw.append(float(ir_raw))

    def refresh(self):
        """
        Recompute filtering + object detection and redraw.
        Call this after add_point() whenever you want a fresh frame.
        """
        with self._lock:
            angles  = list(self._angles)
            us_raw  = list(self._us_raw)
            ir_raw  = list(self._ir_raw)

        if not angles:
            return

        us_filt = self._moving_avg(us_raw, self.window_size)
        objects = self._detect_objects(angles, us_filt, self.obj_gap_deg, self.max_dist)

        with self._lock:
            self.objects = objects

        if self._fig and plt.fignum_exists(self._fig.number):
            self._redraw(angles, us_raw, us_filt, ir_raw, objects)

    # ------------------------------------------------------------------
    # DSP helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _moving_avg(data: list[float], w: int) -> list[float]:
        out = []
        for i, v in enumerate(data):
            sl = data[max(0, i - w + 1): i + 1]
            out.append(sum(sl) / len(sl))
        return out

    @staticmethod
    def _detect_objects(angles, us_filt, gap_deg, max_dist) -> list[dict]:
        """
        Group consecutive angles whose filtered distance < max_dist into
        objects.  Returns list of dicts with keys:
            start_angle, end_angle, mid_angle,
            avg_dist, angular_width, linear_width_cm
        """
        pts = [(a, d) for a, d in zip(angles, us_filt) if d < max_dist]
        if not pts:
            return []

        objs   = []
        group  = [pts[0]]

        for prev, cur in zip(pts, pts[1:]):
            if cur[0] - prev[0] <= gap_deg:
                group.append(cur)
            else:
                if len(group) >= 2:
                    objs.append(group)
                group = [cur]
        if len(group) >= 2:
            objs.append(group)

        result = []
        for g in objs:
            g_angles = [p[0] for p in g]
            g_dists  = [p[1] for p in g]
            mid      = (g_angles[0] + g_angles[-1]) / 2.0
            avg_d    = sum(g_dists) / len(g_dists)
            ang_w    = g_angles[-1] - g_angles[0]
            # chord length — same formula as rad_to_lin in lab7.c
            lin_w    = 2.0 * avg_d * math.tan(math.radians(ang_w / 2.0))
            result.append({
                'start_angle':    g_angles[0],
                'end_angle':      g_angles[-1],
                'mid_angle':      mid,
                'avg_dist':       avg_d,
                'angular_width':  ang_w,
                'linear_width_cm': lin_w,
                'angles':         g_angles,
                'dists':          g_dists,
            })
        return result

    # ------------------------------------------------------------------
    # Figure construction
    # ------------------------------------------------------------------

    def _build_figure(self):
        plt.ion()
        self._fig = plt.figure('CyBot Scan Monitor', figsize=(12, 7))
        self._fig.patch.set_facecolor('#1c1c1e')

        gs = gridspec.GridSpec(2, 2, figure=self._fig,
                               hspace=0.4, wspace=0.35,
                               left=0.07, right=0.97,
                               top=0.93, bottom=0.08)

        self._ax_polar = self._fig.add_subplot(gs[0, 0], projection='polar')
        self._ax_dist  = self._fig.add_subplot(gs[0, 1])
        self._ax_ir    = self._fig.add_subplot(gs[1, :])

        for ax in (self._ax_dist, self._ax_ir):
            ax.set_facecolor('#2c2c2e')
            ax.tick_params(colors='#aeaeb2', labelsize=8)
            for spine in ax.spines.values():
                spine.set_edgecolor('#3a3a3c')

        self._style_polar(self._ax_polar)

        self._fig.suptitle('CyBot real-time scan', color='#f2f2f7',
                           fontsize=13, fontweight='normal', y=0.98)

        plt.show(block=False)

        # Keep the event loop alive until stop() is called
        while self._running and plt.fignum_exists(self._fig.number):
            plt.pause(0.05)

    def _style_polar(self, ax):
        ax.set_facecolor('#2c2c2e')
        ax.set_theta_zero_location('N')
        ax.set_theta_direction(-1)
        # Only show 0–180 °
        ax.set_thetamin(0)
        ax.set_thetamax(180)
        ax.tick_params(colors='#aeaeb2', labelsize=7)
        ax.set_rlabel_position(135)
        ax.grid(color='#3a3a3c', linewidth=0.5)
        ax.spines['polar'].set_edgecolor('#3a3a3c')

    # ------------------------------------------------------------------
    # Redraw
    # ------------------------------------------------------------------

    def _redraw(self, angles, us_raw, us_filt, ir_raw, objects):
        try:
            # ---- polar ------------------------------------------------
            ax = self._ax_polar
            ax.cla()
            self._style_polar(ax)
            ax.set_title('Polar (ultrasound)', color='#aeaeb2',
                         fontsize=9, pad=8)

            r_raw   = np.array(us_raw)
            r_filt  = np.array(us_filt)
            theta   = np.radians(np.array(angles))

            # clip for display
            clip = self.max_dist
            mask = r_filt < clip

            ax.scatter(theta[mask], r_filt[mask],
                       s=6, c='#378ADD', alpha=0.7, zorder=2, label='filtered')
            ax.plot(theta[mask], r_filt[mask],
                    lw=0.8, color='#378ADD', alpha=0.35, zorder=1)

            # highlight detected objects
            for obj in objects:
                obj_theta = np.radians(np.array(obj['angles']))
                obj_r     = np.array(obj['dists'])
                ax.scatter(obj_theta, obj_r,
                           s=20, c='#E24B4A', zorder=3, label='object')
                mid_rad = math.radians(obj['mid_angle'])
                ax.annotate(
                    f"{obj['avg_dist']:.1f}cm",
                    xy=(mid_rad, obj['avg_dist']),
                    xytext=(mid_rad, obj['avg_dist'] * 0.75),
                    color='#ff6b6b', fontsize=7,
                    ha='center',
                    arrowprops=dict(arrowstyle='->', color='#ff6b6b', lw=0.8)
                )

            ax.set_rlim(0, clip)

            # ---- distance vs angle ------------------------------------
            ax2 = self._ax_dist
            ax2.cla()
            ax2.set_facecolor('#2c2c2e')
            ax2.tick_params(colors='#aeaeb2', labelsize=8)
            for spine in ax2.spines.values():
                spine.set_edgecolor('#3a3a3c')

            ax2.plot(angles, us_raw,
                     lw=0.8, color='#378ADD', alpha=0.3, label='raw US')
            ax2.plot(angles, us_filt,
                     lw=1.5, color='#378ADD', alpha=0.9, label=f'avg (n={self.window_size})')

            # shade object regions
            for obj in objects:
                ax2.axvspan(obj['start_angle'], obj['end_angle'],
                            color='#E24B4A', alpha=0.15)

            ax2.axhline(self.max_dist, color='#ffcc00', lw=0.6,
                        linestyle='--', alpha=0.5, label=f'max {self.max_dist}cm')
            ax2.set_xlim(0, 180)
            ax2.set_ylim(0, self.max_dist * 1.1)
            ax2.set_xlabel('Angle (°)', color='#aeaeb2', fontsize=8)
            ax2.set_ylabel('Distance (cm)', color='#aeaeb2', fontsize=8)
            ax2.set_title('Ultrasound vs angle', color='#aeaeb2', fontsize=9)
            ax2.legend(fontsize=7, facecolor='#2c2c2e', edgecolor='#3a3a3c',
                       labelcolor='#aeaeb2', loc='upper right')

            # ---- IR vs angle -----------------------------------------
            ax3 = self._ax_ir
            ax3.cla()
            ax3.set_facecolor('#2c2c2e')
            ax3.tick_params(colors='#aeaeb2', labelsize=8)
            for spine in ax3.spines.values():
                spine.set_edgecolor('#3a3a3c')

            ir_filt = self._moving_avg(ir_raw, self.window_size)
            ax3.fill_between(angles, ir_raw,
                             color='#BA7517', alpha=0.2)
            ax3.plot(angles, ir_raw,
                     lw=0.8, color='#BA7517', alpha=0.4, label='raw IR')
            ax3.plot(angles, ir_filt,
                     lw=1.5, color='#EF9F27', alpha=0.9,
                     label=f'avg (n={self.window_size})')

            for obj in objects:
                ax3.axvspan(obj['start_angle'], obj['end_angle'],
                            color='#E24B4A', alpha=0.12)

            ax3.set_xlim(0, 180)
            ax3.set_xlabel('Angle (°)', color='#aeaeb2', fontsize=8)
            ax3.set_ylabel('IR (ADC counts)', color='#aeaeb2', fontsize=8)
            ax3.set_title('IR sensor vs angle', color='#aeaeb2', fontsize=9)
            ax3.legend(fontsize=7, facecolor='#2c2c2e', edgecolor='#3a3a3c',
                       labelcolor='#aeaeb2', loc='upper right')

            # ---- object summary in figure title -----------------------
            obj_summary = (f"  |  {len(objects)} object(s) detected"
                           if objects else "  |  No objects in range")
            self._fig.suptitle(f'CyBot real-time scan{obj_summary}',
                               color='#f2f2f7', fontsize=13,
                               fontweight='normal', y=0.98)

            self._fig.canvas.draw_idle()
            self._fig.canvas.flush_events()

        except Exception as e:
            print(f"[ScanVisualiser] Redraw error: {e}")


# ===========================================================================
#  ProbePlugin — unchanged except for delegating scan data to the visualiser
# ===========================================================================
class cyBot_Plugin(ProbePlugin):
    def __init__(self):
        super().__init__()
        self.cybot = None
        self.read_thread = None
        self.read_thread_cond = False

        self.address = PluginSettingString("IP Address", "192.168.1.1")
        self.port    = PluginSettingInteger("Port", 288)
        self.timeout = PluginSettingInteger("Timeout (ms)", 10000)

        self.add_setting_pre_connect(self.address)
        self.add_setting_pre_connect(self.port)
        self.add_setting_pre_connect(self.timeout)

        self.log_filename = "cybot_data_log.txt"

    def connect(self):
        try:
            self.cybot = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.cybot.settimeout(self.timeout.value / 1000)
            self.cybot.connect((self.address.value, self.port.value))
            print(f"Connected to cyBot at {self.address.value}:{self.port.value}")
            self.read_thread_cond = True
            self.read_thread = threading.Thread(
                target=self.read_thread_interrupt, daemon=True)
            self.read_thread.start()
        except Exception as e:
            print(f"Failed to connect to cyBot: {e}")
            self.cybot = None

    def read_thread_interrupt(self):
        print(f"Logging started. Saving to {self.log_filename}")
        with open(self.log_filename, "a") as f:
            f.write(f"\n--- Session Started: {datetime.now()} ---\n")
            while self.read_thread_cond:
                try:
                    data = self.cybot.recv(1024)
                    if data:
                        decoded   = data.decode('utf-8', errors='ignore').strip()
                        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                        log_entry = f"[{timestamp}] RX: {decoded}"
                        print(log_entry)
                        f.write(log_entry + "\n")
                        f.flush()
                    else:
                        break
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.read_thread_cond:
                        print(f"Read Error: {e}")
                    break
        print("Logging thread stopped.")

    def disconnect(self):
        self.read_thread_cond = False
        if self.read_thread:
            self.read_thread.join(timeout=2.0)
        if self.cybot:
            try:
                self.cybot.close()
            except Exception:
                pass
            print("Disconnected from cyBot.")

    def send_command(self, cmd):
        if self.cybot:
            self.cybot.send(cmd.encode('utf-8'))

    def get_channel_names(self):
        return super().get_channel_names()

    def get_xaxis_coords(self):
        return super().get_xaxis_coords()

    def get_xaxis_units(self):
        return super().get_xaxis_units()

    def get_yaxis_units(self):
        return super().get_yaxis_units()

    def scan_begin(self):
        return super().scan_begin()

    def scan_end(self):
        return super().scan_end()

    def scan_read_measurement(self, scan_index, scan_location):
        return super().scan_read_measurement(scan_index, scan_location)

    def scan_trigger_and_wait(self, scan_index, scan_location):
        return super().scan_trigger_and_wait(scan_index, scan_location)


# ===========================================================================
#  MotionControllerPlugin — houses the sweep + real-time visualiser
# ===========================================================================

# Regex that matches:  Data: Ultrasound 15.965773 , IR 1091.000000 , Angle 1
_SCAN_RE = re.compile(
    r'Data:\s*Ultrasound\s*([\d.]+)\s*,\s*IR\s*([\d.]+)\s*,\s*Angle\s*(\d+)',
    re.IGNORECASE
)


class motion_controller_plugin(MotionControllerPlugin):

    # --- sweep configuration -------------------------------------------
    SWEEP_START_DEG  = 0
    SWEEP_END_DEG    = 180
    SWEEP_STEP_DEG   = 2      # must divide evenly into 180
    SWEEP_TIMEOUT_S  = 3.0    # seconds to wait for each scan reply

    def __init__(self):
        super().__init__()

        self.address = PluginSettingString("IP Address", "192.168.1.1")
        self.port    = PluginSettingInteger("Port", 288)
        self.timeout = PluginSettingInteger("Timeout (ms)", 10000)

        self.add_setting_pre_connect(self.address)
        self.add_setting_pre_connect(self.port)
        self.add_setting_pre_connect(self.timeout)

        self.log_filename = "cybot_data_log.txt"

        self.cybot = None
        self.read_thread      = None
        self.read_thread_cond = False

        # --- shared visualiser ---
        self._vis = ScanVisualiser()

        # --- pending-response synchronisation --------------------------
        # The read thread deposits decoded scan lines here;
        # do_sweep() picks them up.
        self._scan_event    = threading.Event()
        self._latest_scan   = None          # dict | None
        self._scan_lock     = threading.Lock()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self):
        try:
            self.cybot = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.cybot.settimeout(self.timeout.value / 1000)
            self.cybot.connect((self.address.value, self.port.value))
            print(f"Connected to cyBot at {self.address.value}:{self.port.value}")

            self.read_thread_cond = True
            self.read_thread = threading.Thread(
                target=self.read_thread_interrupt, daemon=True)
            self.read_thread.start()
        except Exception as e:
            print(f"Failed to connect to cyBot: {e}")
            self.cybot = None

    def disconnect(self):
        self.read_thread_cond = False
        if self.read_thread:
            self.read_thread.join(timeout=2.0)
        if self.cybot:
            try:
                self.cybot.close()
            except Exception:
                pass
            print("Disconnected from cyBot.")
        self._vis.stop()

    # ------------------------------------------------------------------
    # RX thread — logs everything, parses scan lines for the visualiser
    # ------------------------------------------------------------------

    def read_thread_interrupt(self):
        print(f"Logging started. Saving to {self.log_filename}")
        buffer = ""
        with open(self.log_filename, "a") as f:
            f.write(f"\n--- Session Started: {datetime.now()} ---\n")
            while self.read_thread_cond:
                try:
                    raw = self.cybot.recv(1024)
                    if not raw:
                        break

                    decoded   = raw.decode('utf-8', errors='ignore')
                    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    log_entry = f"[{timestamp}] RX: {decoded.strip()}"
                    print(log_entry)
                    f.write(log_entry + "\n")
                    f.flush()

                    # Accumulate into buffer to handle TCP fragmentation
                    buffer += decoded
                    # Try to pull complete lines
                    while '\n' in buffer:
                        line, buffer = buffer.split('\n', 1)
                        self._try_parse_scan_line(line)

                    # Also try the fragment in case the bot doesn't always
                    # send newlines (matches anywhere in the raw chunk too)
                    self._try_parse_scan_line(decoded)

                except socket.timeout:
                    continue
                except Exception as e:
                    if self.read_thread_cond:
                        print(f"Read Error: {e}")
                    break
        print("Logging thread stopped.")

    def _try_parse_scan_line(self, text: str):
        """
        If text contains a Data: ... line, extract it, push to visualiser,
        and signal do_sweep() that a response has arrived.
        """
        m = _SCAN_RE.search(text)
        if not m:
            return
        us_cm  = float(m.group(1))
        ir_val = float(m.group(2))
        angle  = int(m.group(3))

        self._vis.add_point(angle, us_cm, ir_val)
        self._vis.refresh()

        with self._scan_lock:
            self._latest_scan = {'angle': angle, 'us': us_cm, 'ir': ir_val}
        self._scan_event.set()

    # ------------------------------------------------------------------
    # Sweep (called by home() — the scan trigger in the scanner GUI)
    # ------------------------------------------------------------------

    def do_sweep(self, step: int = None, start: int = None, end: int = None):
        """
        Autonomously sweeps SWEEP_START_DEG → SWEEP_END_DEG in SWEEP_STEP_DEG
        increments by sending '11<angle>' commands and waiting for each reply.

        Parameters override class-level defaults if supplied.

        Detected objects are printed to stdout and stored in self._vis.objects
        after the sweep completes.
        """
        step  = step  if step  is not None else self.SWEEP_STEP_DEG
        start = start if start is not None else self.SWEEP_START_DEG
        end   = end   if end   is not None else self.SWEEP_END_DEG

        print(f"[Sweep] Starting {start}° → {end}° step {step}°")

        # Open/reset the visualiser window
        self._vis.reset()
        self._vis.start()

        results = []

        for angle in range(start, end + 1, step):
            cmd = f"11{angle}"
            self.send_gcode_command(cmd)

            # Wait for the RX thread to deliver the reply
            self._scan_event.clear()
            got_reply = self._scan_event.wait(timeout=self.SWEEP_TIMEOUT_S)

            if got_reply:
                with self._scan_lock:
                    pt = dict(self._latest_scan)
                results.append(pt)
                print(f"[Sweep] {angle:>4}°  US={pt['us']:.3f}cm  IR={pt['ir']:.0f}")
            else:
                print(f"[Sweep] {angle:>4}°  — timeout, skipping")

        print("[Sweep] Complete.")
        self._print_object_report()
        return results

    def _print_object_report(self):
        objs = self._vis.objects
        if not objs:
            print("[Objects] No objects detected in range.")
            return
        print(f"\n[Objects] {len(objs)} object(s) detected:")
        print(f"  {'#':<4} {'Mid angle':>10} {'Avg dist':>10} {'Ang width':>10} "
              f"{'Lin width':>12}")
        print("  " + "-" * 52)
        for i, o in enumerate(objs, 1):
            print(f"  {i:<4} {o['mid_angle']:>9.1f}°  {o['avg_dist']:>8.2f}cm  "
                  f"{o['angular_width']:>8.1f}°  {o['linear_width_cm']:>10.2f}cm")
        print()

    # ------------------------------------------------------------------
    # ADC averaging (from original plugin — kept intact)
    # ------------------------------------------------------------------

    @staticmethod
    def apply_adc_averaging(fp, window_size=5):
        raw_values = []
        try:
            with open(fp, 'r') as f:
                for line in f:
                    if "Data:" in line:
                        parts = line.split("Data:")[1]
                        if len(parts) > 1:
                            try:
                                value = float(parts[1].strip().split()[0])
                                raw_values.append(value)
                            except Exception as e:
                                print(f"Error occurred while reading file: {e}")
            if len(raw_values) < window_size:
                print("Not enough data points for averaging.")
                return None
            smoothed = []
            for i in range(len(raw_values)):
                start_idx = max(0, i - window_size + 1)
                window    = raw_values[start_idx: i + 1]
                smoothed.append(round(sum(window) / len(window), 4))
            return smoothed
        except Exception as e:
            print(f"Error occurred while reading file: {e}")
            return None

    # ------------------------------------------------------------------
    # MotionControllerPlugin interface
    # ------------------------------------------------------------------

    def get_axis_display_names(self) -> tuple[str, ...]:
        pass

    def get_axis_units(self) -> tuple[str, ...]:
        pass

    def set_velocity(self, velocities: dict[int, float] = None) -> None:
        pass

    def set_acceleration(self, accels: dict[int, float] = None) -> None:
        pass

    def move_absolute(self, move_dist: dict[int, float]) -> dict[int, float] | None:
        for key, val in move_dist.items():
            raw_value     = int(abs(val))
            raw_value_str = str(raw_value)
            is_negative   = val < 0

            if key == 0:        # X Axis (Rotation)
                prefix = "r"
            elif key == 1:      # Y Axis (movement)
                prefix = "mb" if is_negative else "mf"
            else:
                print(f"Warning: Unexpected dictionary key '{key}'.")
                continue

            if prefix == 'mf':
                cmd = '00' + raw_value_str
            elif prefix == 'mb':
                cmd = '01' + raw_value_str
            else:               # rotation
                cmd = '10' + raw_value_str

            print(f"sending this command: {cmd}")
            self.send_gcode_command(cmd)

    def move_relative(self, move_pos: dict[int, float]) -> dict[int, float] | None:
        pass

    def get_current_positions(self) -> tuple[float, ...]:
        pass

    def is_moving(self, axis=None) -> bool:
        pass

    def get_endstop_minimums(self) -> tuple[float, ...]:
        pass

    def get_endstop_maximums(self) -> tuple[float, ...]:
        pass

    def set_config(self, amps, idle_p, idle_time):
        pass

    def send_gcode_command(self, command):
        if isinstance(command, int):
            command = str(command)
        if self.cybot:
            self.cybot.send((command + "\n").encode('utf-8'))

    def emergency_stop(self):
        pass

    def home(self, axes=None):
        
        sweep_thread = threading.Thread(
            target=self.do_sweep, daemon=True)
        sweep_thread.start()