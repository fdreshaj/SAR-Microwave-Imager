# scan_pattern_quadrature.py
#
# Quadrature Bistatic Scan Pattern
#
# ═══════════════════════════════════════════════════════════════════════════
# PHYSICAL SETUP
# ═══════════════════════════════════════════════════════════════════════════
#
#   X rail  (Rx) — X1 and X2 antennas, tandem, step along X (slow axis)
#   Y rail  (Tx) — Y1 and Y2 antennas, tandem, serpentine along Y (fast axis)
#
#   At each gantry position the VNA captures 4 S-parameters:
#       S(X1 ← Y1),  S(X1 ← Y2),  S(X2 ← Y1),  S(X2 ← Y2)
#
#   Antenna offsets from the gantry centre (all user-configurable):
#
#       X rail:   X1 at  gantry_x − x_ant_offset   (e.g. left  antenna)
#                 X2 at  gantry_x + x_ant_offset   (e.g. right antenna)
#
#       Y rail:   Y1 at  gantry_y − y_ant_offset   (e.g. front antenna)
#                 Y2 at  gantry_y + y_ant_offset   (e.g. rear  antenna)
#
#   Set offsets to 0 if the antennas are co-located at the carriage centre.
#
# ═══════════════════════════════════════════════════════════════════════════
# SCAN SEQUENCE
# ═══════════════════════════════════════════════════════════════════════════
#
#   For each X column (slow axis, left → right):
#       Move X rail to column position
#       Serpentine Y rail:
#           even columns: Y sweeps top → bottom
#           odd  columns: Y sweeps bottom → top
#       At each Y step: trigger VNA → record 4 S-params
#
#   This matches the MATLAB "Square opposite sides" geometry:
#       Tx (Y rail) traces the horizontal edges of the aperture square
#       Rx (X rail) traces the vertical   edges of the aperture square
#
# ═══════════════════════════════════════════════════════════════════════════
# MATRIX FORMAT  (3, N)  — compatible with scanner.run_scan()
# ═══════════════════════════════════════════════════════════════════════════
#
#   Row 0 : X step index  (axis 0, slow — X rail / Rx)
#   Row 1 : Y step index  (axis 1, fast — Y rail / Tx)
#   Row 2 : always 0.0   (z placeholder — scanner.py writes this to HDF5
#                          z_data; post-processing can ignore it)
#
#   scanner.run_scan() diffs consecutive columns and issues move_absolute()
#   calls exactly as it does for scan_pattern_1 — no changes to scanner.py.
#
#   The 4 S-parameter measurements per point are collected by the VNA probe
#   plugin (S21/S31/S12/S32 or however the VNA channels are labelled).
#   They are stored by scanner.run_scan() in /Data/<s_param_name>_real/imag.
#
# ═══════════════════════════════════════════════════════════════════════════
# SETTINGS  (all pre-connect)
# ═══════════════════════════════════════════════════════════════════════════
#
#   X axis length (mm)        — total travel of the X rail (Rx slow axis)
#   Y axis length (mm)        — total travel of the Y rail (Tx fast axis)
#   Step size (mm)            — spatial sampling interval (same both axes)
#   X antenna offset (mm)     — half-separation between X1 and X2
#                               X1 at  centre − offset,  X2 at  centre + offset
#   Y antenna offset (mm)     — half-separation between Y1 and Y2
#                               Y1 at  centre − offset,  Y2 at  centre + offset

import sys
import types
import tkinter as tk
from tkinter import messagebox
import numpy as np
import matplotlib.pyplot as plt

# ── Standalone stub registration ───────────────────────────────────────────
# When run directly (python scan_pattern_quadrature.py) the scanner package
# is not on the path.  Register lightweight stubs BEFORE the imports below
# so they resolve correctly whether run standalone or loaded as a plugin.
if "scanner" not in sys.modules:

    class _PluginSettingFloat:
        def __init__(self, label, default, **kw):
            self.display_label = label
            self._val = str(default)
        def get_value_as_string(self):
            return self._val
        def set_value_from_string(self, v):
            self._val = v
        @staticmethod
        def get_value_as_string(s):          # noqa: F811  (matches real API)
            return s._val

    class _PluginSettingString(_PluginSettingFloat):
        @staticmethod
        def get_value_as_string(s):          # noqa: F811
            return s._val

    class _ScanPatternControllerPlugin:
        def __init__(self):
            self.settings_pre_connect  = []
            self.settings_post_connect = []
        def add_setting_pre_connect(self, s):
            self.settings_pre_connect.append(s)
        def add_setting_post_connect(self, s):
            self.settings_post_connect.append(s)

    _scanner_mod = types.ModuleType("scanner")
    _spc_mod     = types.ModuleType("scanner.scan_pattern_controller")
    _ps_mod      = types.ModuleType("scanner.plugin_setting")

    _spc_mod.ScanPatternControllerPlugin = _ScanPatternControllerPlugin
    _ps_mod.PluginSettingFloat           = _PluginSettingFloat
    _ps_mod.PluginSettingString          = _PluginSettingString

    sys.modules["scanner"]                          = _scanner_mod
    sys.modules["scanner.scan_pattern_controller"]  = _spc_mod
    sys.modules["scanner.plugin_setting"]           = _ps_mod

from scanner.scan_pattern_controller import ScanPatternControllerPlugin
from scanner.plugin_setting import PluginSettingFloat, PluginSettingString


class ScanPattern(ScanPatternControllerPlugin):
    """
    Quadrature bistatic scan pattern.

    Y rail (Y1+Y2, Tx) is the fast serpentine axis.
    X rail (X1+X2, Rx) is the slow stepping axis.
    4 S-parameters captured per point: S(X1←Y1), S(X1←Y2), S(X2←Y1), S(X2←Y2).

    Produces a (3, N) matrix identical in format to scan_pattern_1,
    consumed by scanner.run_scan() without any changes to scanner.py.
    """

    _is_connected: bool

    def __init__(self):
        super().__init__()
        self._is_connected = False

        # ── Settings ──────────────────────────────────────────────────────
        self.x_length = PluginSettingFloat("X axis length (mm): ", 200.0)
        self.y_length = PluginSettingFloat("Y axis length (mm): ", 200.0)
        self.step_size = PluginSettingFloat("Step size (mm): ", 2.0)
        self.x_ant_offset = PluginSettingFloat(
            "X antenna offset (mm): ", 0.0
        )   # half-gap between X1 and X2
        self.y_ant_offset = PluginSettingFloat(
            "Y antenna offset (mm): ", 0.0
        )   # half-gap between Y1 and Y2

        for s in [self.x_length, self.y_length, self.step_size,
                  self.x_ant_offset, self.y_ant_offset]:
            self.add_setting_pre_connect(s)

        # ── Outputs ────────────────────────────────────────────────────────
        self.matrix: np.ndarray | None = None   # (3, N)
        self.time_est: float = 0.0

        # Per-point bistatic geometry — stored for HDF5 metadata / plotting.
        # Each array has length N (one entry per scan point).
        self.x1_positions: np.ndarray | None = None   # X1 physical x (mm)
        self.x2_positions: np.ndarray | None = None   # X2 physical x (mm)
        self.y1_positions: np.ndarray | None = None   # Y1 physical y (mm)
        self.y2_positions: np.ndarray | None = None   # Y2 physical y (mm)

    # ─────────────────────────────────────────────────────────────────────
    # ScanPatternControllerPlugin interface
    # ─────────────────────────────────────────────────────────────────────

    def connect(self) -> None:
        x_len      = float(PluginSettingFloat.get_value_as_string(self.x_length))
        y_len      = float(PluginSettingFloat.get_value_as_string(self.y_length))
        step       = float(PluginSettingFloat.get_value_as_string(self.step_size))
        x_off      = float(PluginSettingFloat.get_value_as_string(self.x_ant_offset))
        y_off      = float(PluginSettingFloat.get_value_as_string(self.y_ant_offset))

        # ── Validate divisibility ─────────────────────────────────────────
        x_pts_f = x_len / step
        y_pts_f = y_len / step
        if not np.isclose(x_pts_f, round(x_pts_f)) or \
           not np.isclose(y_pts_f, round(y_pts_f)):
            self._popup(
                "Error",
                f"Axis lengths must be evenly divisible by step size.\n"
                f"X: {x_len} / {step} = {x_pts_f:.4f}\n"
                f"Y: {y_len} / {step} = {y_pts_f:.4f}"
            )
            self.disconnect()
            return

        x_steps = int(round(x_pts_f)) + 1   # number of X sample columns
        y_steps = int(round(y_pts_f)) + 1   # number of Y sample rows

        # ── Build scan matrix ─────────────────────────────────────────────
        self.matrix, \
        self.x1_positions, self.x2_positions, \
        self.y1_positions, self.y2_positions = \
            self._build_matrix(x_steps, y_steps, step, x_off, y_off)

        N = self.matrix.shape[1]
        self.time_est = self._time_estimate(N, step)

        # ── Bistatic separation stats (all 4 pairs) ───────────────────────
        # S(X1←Y1)
        sep_x1y1 = np.sqrt((self.x1_positions - self.matrix[0] * step)**2 +
                           (self.y1_positions - self.matrix[1] * step)**2)
        sep_x1y2 = np.sqrt((self.x1_positions - self.matrix[0] * step)**2 +
                           (self.y2_positions - self.matrix[1] * step)**2)
        sep_x2y1 = np.sqrt((self.x2_positions - self.matrix[0] * step)**2 +
                           (self.y1_positions - self.matrix[1] * step)**2)
        sep_x2y2 = np.sqrt((self.x2_positions - self.matrix[0] * step)**2 +
                           (self.y2_positions - self.matrix[1] * step)**2)

        print(f"\nQuadrature scan matrix built:")
        print(f"  X rail (Rx):    {x_steps} columns,  {x_len} mm,  step {step} mm")
        print(f"  Y rail (Tx):    {y_steps} rows,     {y_len} mm,  step {step} mm")
        print(f"  X ant offset:   ±{x_off} mm  (X1 at −offset, X2 at +offset)")
        print(f"  Y ant offset:   ±{y_off} mm  (Y1 at −offset, Y2 at +offset)")
        print(f"  Total points:   {N}")
        print(f"  Time estimate:  {self.time_est} hours")
        print(f"  S-params/pt:    S(X1←Y1), S(X1←Y2), S(X2←Y1), S(X2←Y2)")
        print(f"  Bistatic sep X1←Y1: {sep_x1y1.min():.1f}–{sep_x1y1.max():.1f} mm")
        print(f"  Bistatic sep X2←Y2: {sep_x2y2.min():.1f}–{sep_x2y2.max():.1f} mm")

        self._popup(
            "Quadrature Scan Ready",
            f"X rail (Rx):   {x_steps} cols × {x_len} mm\n"
            f"Y rail (Tx):   {y_steps} rows × {y_len} mm\n"
            f"Step size:     {step} mm\n"
            f"X ant offset:  ±{x_off} mm\n"
            f"Y ant offset:  ±{y_off} mm\n"
            f"Total points:  {N}\n"
            f"S-params/pt:   4  (X1←Y1, X1←Y2, X2←Y1, X2←Y2)\n"
            f"Time estimate: {self.time_est} hours"
        )

        self._is_connected = True
        print(f"ScanPattern connected: {self._is_connected}")

    def disconnect(self) -> None:
        self._is_connected = False

    def is_connected(self) -> bool:
        return self._is_connected

    # ─────────────────────────────────────────────────────────────────────
    # Matrix builder
    # ─────────────────────────────────────────────────────────────────────

    def _build_matrix(
        self,
        x_steps: int,
        y_steps: int,
        step: float,
        x_off: float,
        y_off: float,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Build the (3, N) scan matrix and per-point antenna positions.

        Scan order:
          Outer loop: X columns  0 … x_steps-1  (slow axis, X rail / Rx)
          Inner loop: Y rows     serpentine      (fast axis, Y rail / Tx)
            even X col → Y sweeps 0 → y_steps-1  (top to bottom)
            odd  X col → Y sweeps y_steps-1 → 0  (bottom to top)

        Gantry position at step (xi, yi):
            gantry_x = xi * step   (centre of X carriage, mm)
            gantry_y = yi * step   (centre of Y carriage, mm)

        Antenna physical positions:
            X1 at  gantry_x − x_off,  gantry_y  (Rx, left)
            X2 at  gantry_x + x_off,  gantry_y  (Rx, right)
            Y1 at  gantry_x,  gantry_y − y_off  (Tx, front)
            Y2 at  gantry_x,  gantry_y + y_off  (Tx, rear)

        Returns
        -------
        matrix      : (3, N)  — rows [x_idx, y_idx, 0.0]
        x1_pos      : (N,)    — X1 physical x position (mm)
        x2_pos      : (N,)    — X2 physical x position (mm)
        y1_pos      : (N,)    — Y1 physical y position (mm)
        y2_pos      : (N,)    — Y2 physical y position (mm)
        """
        N = x_steps * y_steps

        x_idx  = np.empty(N, dtype=float)
        y_idx  = np.empty(N, dtype=float)
        x1_pos = np.empty(N, dtype=float)
        x2_pos = np.empty(N, dtype=float)
        y1_pos = np.empty(N, dtype=float)
        y2_pos = np.empty(N, dtype=float)

        idx = 0
        for xi in range(x_steps):
            gantry_x = xi * step

            # Serpentine: even columns top→bottom, odd columns bottom→top
            y_range = range(y_steps) if xi % 2 == 0 \
                      else range(y_steps - 1, -1, -1)

            for yi in y_range:
                gantry_y = yi * step

                x_idx[idx]  = float(xi)
                y_idx[idx]  = float(yi)

                # X rail antennas — offset along X from gantry centre
                x1_pos[idx] = gantry_x - x_off   # Rx left
                x2_pos[idx] = gantry_x + x_off   # Rx right

                # Y rail antennas — offset along Y from gantry centre
                y1_pos[idx] = gantry_y - y_off   # Tx front
                y2_pos[idx] = gantry_y + y_off   # Tx rear

                idx += 1

        z_row  = np.zeros(N, dtype=float)
        matrix = np.array([x_idx, y_idx, z_row], dtype=float)

        return matrix, x1_pos, x2_pos, y1_pos, y2_pos

    # ─────────────────────────────────────────────────────────────────────
    # Utilities
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def _time_estimate(total_points: int, step_size: float) -> float:
        """Matches scan_pattern_1: t = 2*sqrt(step/10) per point. Returns hours."""
        t_per_point = 2.0 * np.sqrt(step_size / 10.0)
        return float(np.round(total_points * t_per_point / 3600.0, 3))

    @staticmethod
    def _popup(title: str, message: str) -> None:
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo(title, message)
        root.destroy()

    # ─────────────────────────────────────────────────────────────────────
    # Visualisation
    # ─────────────────────────────────────────────────────────────────────

    def plot_scan(self, stride: int = 1) -> None:
        """
        Three-panel figure:
          Left   — Gantry travel path (serpentine, coloured by column)
          Centre — Physical antenna positions: X1, X2 (Rx) and Y1, Y2 (Tx)
          Right  — Bistatic separation heatmap for each of the 4 S-param pairs
        """
        if self.matrix is None:
            print("No matrix — call connect() first.")
            return

        step = float(PluginSettingFloat.get_value_as_string(self.step_size))

        gx = self.matrix[0, ::stride] * step   # gantry X (mm)
        gy = self.matrix[1, ::stride] * step   # gantry Y (mm)

        x1 = self.x1_positions[::stride]
        x2 = self.x2_positions[::stride]
        y1 = self.y1_positions[::stride]
        y2 = self.y2_positions[::stride]

        # Bistatic separations for all 4 pairs (mm)
        # X antennas sit at (x1/x2, gantry_y); Y antennas at (gantry_x, y1/y2)
        gx_full = self.matrix[0] * step
        gy_full = self.matrix[1] * step
        sep = {
            "X1←Y1": np.sqrt((x1 - gx_full[::stride])**2 + (gy[::stride] - y1)**2),  # noqa
            "X1←Y2": np.sqrt((x1 - gx_full[::stride])**2 + (gy[::stride] - y2)**2),
            "X2←Y1": np.sqrt((x2 - gx_full[::stride])**2 + (gy[::stride] - y1)**2),
            "X2←Y2": np.sqrt((x2 - gx_full[::stride])**2 + (gy[::stride] - y2)**2),
        }

        fig = plt.figure(figsize=(20, 6))
        gs  = fig.add_gridspec(1, 3, wspace=0.35)

        # ── Panel 1: Gantry path coloured by X column ─────────────────────
        ax1 = fig.add_subplot(gs[0])
        col_idx = (self.matrix[0, ::stride] * step).astype(int)
        sc1 = ax1.scatter(gx, gy, c=col_idx, cmap='viridis',
                          s=4, alpha=0.7)
        ax1.plot(gx, gy, '-', color='grey', linewidth=0.4, alpha=0.4)
        ax1.scatter(gx[0],  gy[0],  color='green', s=80, zorder=5,
                    label='Start')
        ax1.scatter(gx[-1], gy[-1], color='red',   s=80, zorder=5,
                    label='End')
        plt.colorbar(sc1, ax=ax1, label='X column (mm)')
        ax1.set_title("Gantry travel path\n(serpentine, fast=Y)", fontsize=10)
        ax1.set_xlabel("Gantry X — X rail / Rx (mm)")
        ax1.set_ylabel("Gantry Y — Y rail / Tx (mm)")
        ax1.set_aspect("equal")
        ax1.legend(fontsize=8)
        ax1.grid(True, alpha=0.25)

        # ── Panel 2: Physical antenna positions ────────────────────────────
        ax2 = fig.add_subplot(gs[1])
        ax2.scatter(x1, gy, s=6, color='steelblue',  alpha=0.5,
                    label='X1 Rx (left)')
        ax2.scatter(x2, gy, s=6, color='dodgerblue', alpha=0.5,
                    label='X2 Rx (right)')
        ax2.scatter(gx, y1, s=6, color='tomato',     alpha=0.5,
                    label='Y1 Tx (front)')
        ax2.scatter(gx, y2, s=6, color='firebrick',  alpha=0.5,
                    label='Y2 Tx (rear)')
        ax2.set_title("Physical antenna positions\nX1/X2=Rx (blue), Y1/Y2=Tx (red)",
                      fontsize=10)
        ax2.set_xlabel("X (mm)")
        ax2.set_ylabel("Y (mm)")
        ax2.set_aspect("equal")
        ax2.legend(fontsize=7, loc='upper right')
        ax2.grid(True, alpha=0.25)

        # ── Panel 3: Bistatic separation for all 4 pairs ──────────────────
        ax3 = fig.add_subplot(gs[2])
        colors = ['steelblue', 'dodgerblue', 'tomato', 'firebrick']
        for (label, s), c in zip(sep.items(), colors):
            ax3.plot(range(len(s)), s, linewidth=0.7, alpha=0.8,
                     label=label, color=c)
        ax3.set_title("Bistatic separation per point\n(all 4 S-param pairs)",
                      fontsize=10)
        ax3.set_xlabel("Point index")
        ax3.set_ylabel("Separation (mm)")
        ax3.legend(fontsize=8)
        ax3.grid(True, alpha=0.25)

        fig.suptitle("Quadrature Bistatic Scan — Physical Geometry",
                     fontsize=13, fontweight='bold')
        plt.tight_layout()
        plt.show()


# ═══════════════════════════════════════════════════════════════════════════
# Standalone preview  —  python scan_pattern_quadrature.py
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    from tkinter import ttk
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    import matplotlib.gridspec as mgridspec

    # ── Standalone matrix builder (raw floats, no PluginSetting wrapper) ───
    def _build_matrix_direct(x_len, y_len, step, x_off, y_off):
        """Same logic as ScanPattern._build_matrix but takes raw floats."""
        x_steps = int(round(x_len / step)) + 1
        y_steps = int(round(y_len / step)) + 1
        N = x_steps * y_steps

        x_idx  = np.empty(N, dtype=float)
        y_idx  = np.empty(N, dtype=float)
        x1_pos = np.empty(N, dtype=float)
        x2_pos = np.empty(N, dtype=float)
        y1_pos = np.empty(N, dtype=float)
        y2_pos = np.empty(N, dtype=float)

        idx = 0
        for xi in range(x_steps):
            gx = xi * step
            y_range = range(y_steps) if xi % 2 == 0 \
                      else range(y_steps - 1, -1, -1)
            for yi in y_range:
                gy = yi * step
                x_idx[idx]  = float(xi)
                y_idx[idx]  = float(yi)
                x1_pos[idx] = gx - x_off
                x2_pos[idx] = gx + x_off
                y1_pos[idx] = gy - y_off
                y2_pos[idx] = gy + y_off
                idx += 1

        matrix = np.array([x_idx, y_idx, np.zeros(N)], dtype=float)
        return matrix, x1_pos, x2_pos, y1_pos, y2_pos

    def _time_est(N, step):
        return round(N * 2.0 * np.sqrt(step / 10.0) / 3600.0, 3)

    # ── Main window ────────────────────────────────────────────────────────
    root = tk.Tk()
    root.title("Quadrature Scan Pattern — Preview")
    root.resizable(False, False)

    # ── Left panel: inputs ─────────────────────────────────────────────────
    frm = ttk.LabelFrame(root, text="Scan Parameters", padding=12)
    frm.grid(row=0, column=0, padx=14, pady=14, sticky="ns")

    fields = [
        ("X axis length (mm)",    "200"),
        ("Y axis length (mm)",    "200"),
        ("Step size (mm)",        "10"),
        ("X antenna offset (mm)", "0"),
        ("Y antenna offset (mm)", "0"),
    ]
    entries = {}
    for r, (label, default) in enumerate(fields):
        ttk.Label(frm, text=label).grid(row=r, column=0, sticky="e",
                                        padx=(0, 8), pady=4)
        var = tk.StringVar(value=default)
        ent = ttk.Entry(frm, textvariable=var, width=10)
        ent.grid(row=r, column=1, sticky="w", pady=4)
        entries[label] = var

    # Stats labels
    sep = ttk.Separator(frm, orient="horizontal")
    sep.grid(row=len(fields), column=0, columnspan=2, sticky="ew",
             pady=(12, 6))

    lbl_points   = ttk.Label(frm, text="Total points: —",
                              font=("Helvetica", 10, "bold"))
    lbl_points.grid(row=len(fields)+1, column=0, columnspan=2, pady=2)

    lbl_time     = ttk.Label(frm, text="Est. time:    —")
    lbl_time.grid(row=len(fields)+2, column=0, columnspan=2, pady=2)

    lbl_xcols    = ttk.Label(frm, text="X columns:    —")
    lbl_xcols.grid(row=len(fields)+3, column=0, columnspan=2, pady=2)

    lbl_yrows    = ttk.Label(frm, text="Y rows:       —")
    lbl_yrows.grid(row=len(fields)+4, column=0, columnspan=2, pady=2)

    lbl_err      = ttk.Label(frm, text="", foreground="red",
                              wraplength=200)
    lbl_err.grid(row=len(fields)+5, column=0, columnspan=2, pady=(6, 0))

    # ── Right panel: matplotlib canvas ────────────────────────────────────
    fig = plt.Figure(figsize=(14, 5), dpi=96)
    canvas = FigureCanvasTkAgg(fig, master=root)
    canvas.get_tk_widget().grid(row=0, column=1, padx=(0, 14), pady=14)

    # ── Generate / update ──────────────────────────────────────────────────
    def generate(*_):
        lbl_err.config(text="")
        try:
            x_len = float(entries["X axis length (mm)"].get())
            y_len = float(entries["Y axis length (mm)"].get())
            step  = float(entries["Step size (mm)"].get())
            x_off = float(entries["X antenna offset (mm)"].get())
            y_off = float(entries["Y antenna offset (mm)"].get())
        except ValueError:
            lbl_err.config(text="All fields must be numbers.")
            return

        if step <= 0:
            lbl_err.config(text="Step size must be > 0.")
            return

        x_pts_f = x_len / step
        y_pts_f = y_len / step
        if not np.isclose(x_pts_f, round(x_pts_f)) or \
           not np.isclose(y_pts_f, round(y_pts_f)):
            lbl_err.config(
                text=f"Lengths not divisible by step.\n"
                     f"X: {x_len}/{step}={x_pts_f:.3f}\n"
                     f"Y: {y_len}/{step}={y_pts_f:.3f}"
            )
            return

        matrix, x1, x2, y1, y2 = _build_matrix_direct(
            x_len, y_len, step, x_off, y_off
        )
        N       = matrix.shape[1]
        x_steps = int(round(x_pts_f)) + 1
        y_steps = int(round(y_pts_f)) + 1
        t_est   = _time_est(N, step)

        lbl_points.config(text=f"Total points: {N:,}")
        lbl_time.config(  text=f"Est. time:    {t_est} hrs")
        lbl_xcols.config( text=f"X columns:    {x_steps}")
        lbl_yrows.config( text=f"Y rows:       {y_steps}")

        # ── Draw plots ─────────────────────────────────────────────────────
        fig.clear()
        gs = mgridspec.GridSpec(1, 3, figure=fig, wspace=0.38,
                                left=0.06, right=0.97,
                                top=0.88, bottom=0.12)

        gx = matrix[0] * step
        gy = matrix[1] * step

        # Panel 1 — gantry travel path
        ax1 = fig.add_subplot(gs[0])
        sc  = ax1.scatter(gx, gy, c=matrix[0], cmap="viridis",
                          s=max(1, 40 - N // 200), alpha=0.75)
        ax1.plot(gx, gy, "-", color="grey", lw=0.35, alpha=0.35)
        ax1.scatter(gx[0],  gy[0],  color="limegreen", s=70,
                    zorder=5, label="Start")
        ax1.scatter(gx[-1], gy[-1], color="red",       s=70,
                    zorder=5, label="End")
        fig.colorbar(sc, ax=ax1, label="X col index", pad=0.02,
                     fraction=0.046)
        ax1.set_title(f"Gantry path  ({N:,} pts)", fontsize=9)
        ax1.set_xlabel("X — Rx rail (mm)", fontsize=8)
        ax1.set_ylabel("Y — Tx rail (mm)", fontsize=8)
        ax1.set_aspect("equal")
        ax1.legend(fontsize=7)
        ax1.grid(True, alpha=0.2)

        # Panel 2 — antenna positions
        ax2 = fig.add_subplot(gs[1])
        stride = max(1, N // 2000)
        ax2.scatter(x1[::stride], gy[::stride], s=3,
                    color="steelblue",  alpha=0.5, label="X1 Rx (−off)")
        ax2.scatter(x2[::stride], gy[::stride], s=3,
                    color="dodgerblue", alpha=0.5, label="X2 Rx (+off)")
        ax2.scatter(gx[::stride], y1[::stride], s=3,
                    color="tomato",     alpha=0.5, label="Y1 Tx (−off)")
        ax2.scatter(gx[::stride], y2[::stride], s=3,
                    color="firebrick",  alpha=0.5, label="Y2 Tx (+off)")
        ax2.set_title("Antenna positions", fontsize=9)
        ax2.set_xlabel("X (mm)", fontsize=8)
        ax2.set_ylabel("Y (mm)", fontsize=8)
        ax2.set_aspect("equal")
        ax2.legend(fontsize=6, loc="upper right")
        ax2.grid(True, alpha=0.2)

        # Panel 3 — bistatic separations
        ax3 = fig.add_subplot(gs[2])
        pairs = {
            "X1←Y1": np.sqrt((x1 - gx)**2 + (gy - y1)**2),
            "X1←Y2": np.sqrt((x1 - gx)**2 + (gy - y2)**2),
            "X2←Y1": np.sqrt((x2 - gx)**2 + (gy - y1)**2),
            "X2←Y2": np.sqrt((x2 - gx)**2 + (gy - y2)**2),
        }
        colors = ["steelblue", "dodgerblue", "tomato", "firebrick"]
        pt = np.arange(N)
        for (lbl, s), c in zip(pairs.items(), colors):
            ax3.plot(pt[::stride], s[::stride],
                     lw=0.8, alpha=0.85, label=lbl, color=c)
        ax3.set_title("Bistatic separation (all 4 pairs)", fontsize=9)
        ax3.set_xlabel("Point index", fontsize=8)
        ax3.set_ylabel("Separation (mm)", fontsize=8)
        ax3.legend(fontsize=7)
        ax3.grid(True, alpha=0.2)

        fig.suptitle("Quadrature Bistatic Scan — Preview",
                     fontsize=11, fontweight="bold")
        canvas.draw()

    # Generate button
    btn = ttk.Button(frm, text="Generate  ▶", command=generate)
    btn.grid(row=len(fields)+6, column=0, columnspan=2, pady=(14, 2),
             ipadx=10, ipady=4)

    # Bind Enter key to generate
    root.bind("<Return>", generate)

    # Draw initial plot with defaults
    generate()

    root.mainloop()