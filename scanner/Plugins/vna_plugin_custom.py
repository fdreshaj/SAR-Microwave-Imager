"""
vna_plugin.py
=============
VNA plugin for Scan_Controller_Probe_Main.

Architecture is identical to cyBot_Plugin.py:
  - TCP socket  (VNA firmware exposes a socket server over its USB-UART bridge
    on the STM32H7; same transport layer the CyBot uses)
  - Daemon read_thread with read_thread_cond boolean flag
  - recv_buf string accumulator split on newlines
  - threading.Event() for TX/RX synchronisation  (ok_received, sweep_finished)
  - MotionControllerPlugin base class
  - PluginSettingString / PluginSettingInteger for UI settings
  - send_command() mirrors send_gcode_command()

All three responsibilities live in this one file:
  1. Socket comms with the VNA
  2. SOLT one-port calibration + de-embedding
  3. NRW material characterisation

VNA firmware protocol  (ASCII lines over TCP, newline-terminated)
-----------------------------------------------------------------
  Host → VNA   "CONFIG <f_start_hz> <f_stop_hz> <n_points>\\n"
  VNA  → Host  "OK\\n"

  Host → VNA   "SWEEP\\n"
  VNA  → Host  "SWEEP_START <Nf>\\n"
               "F <freq_hz> <re_S11> <im_S11>\\n"   (× Nf)
               "SWEEP_END\\n"

  Host → VNA   "IDENTIFY\\n"
  VNA  → Host  "VNA_ISU_V1\\n"

The STM32H7 UART interrupt (HAL_UART_Receive_IT) fires per character.

HDF5 output  (/scan/vna/)
--------------------------
  freqs       (Nf,)          float64   Hz
  S11_raw     (Nx,Ny,Nf)     complex128
  S11_cal     (Nx,Ny,Nf)     complex128  SOLT-corrected + de-embedded
  eps_r       (Nx,Ny,Nf)     complex128  NRW permittivity
  mu_r        (Nx,Ny,Nf)     complex128  NRW permeability
  cal/e00     (Nf,)          complex128
  cal/e11     (Nf,)          complex128
  cal/Delta   (Nf,)          complex128
  attrs: f_start_hz, f_stop_hz, n_points, delay_m, sample_length_m

"""

from __future__ import annotations

import logging
import threading
from typing import Optional

import h5py
import numpy as np

from scanner.plugin_setting import PluginSettingString, PluginSettingInteger
from scanner.motion_controller import MotionControllerPlugin

log = logging.getLogger(__name__)

C_LIGHT = 299_792_458.0   # m/s


def _nrw(
    S11: np.ndarray,
    S21: np.ndarray,
    freqs: np.ndarray,
    L: float,
    lamb_c: float = np.inf,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Nicolson-Ross-Weir: return (eps_r, mu_r) from calibrated S-parameters.

    Parameters
    ----------
    S11, S21  : complex (Nf,)  calibrated, de-embedded
    freqs     : float   (Nf,)  Hz
    L         : float          sample length in metres
    lamb_c    : float          coax cutoff wavelength (inf for TEM)
    """
    lambda_0      = C_LIGHT / freqs
    inv_lamb_c_sq = np.zeros_like(lambda_0, dtype=complex)
    if not np.isinf(lamb_c):
        inv_lamb_c_sq[:] = (1.0 / lamb_c) ** 2

    V1 = S21 + S11
    V2 = S21 - S11

    denom_X = np.where(np.abs(V1 - V2) < 1e-12, 1e-12 + 0j, V1 - V2)
    X = (1.0 - V1 * V2) / denom_X

    sqrt_term = np.sqrt(X**2 - 1.0 + 0j)
    Gamma_p   = X + sqrt_term
    Gamma_n   = X - sqrt_term
    Gamma     = np.where(np.abs(Gamma_p) <= 1.0, Gamma_p, Gamma_n)

    denom_z1 = np.where(
        np.abs(1.0 - Gamma * (S11 + S21)) < 1e-14,
        1e-14 + 0j,
        1.0 - Gamma * (S11 + S21),
    )
    z1 = (S11 + S21 - Gamma) / denom_z1

    with np.errstate(divide="ignore", invalid="ignore"):
        log_z1 = np.log(1.0 / (z1 + 1e-300))
    inv_lamb_sq = -((1.0 / (2.0 * np.pi * L)) * log_z1) ** 2

    Lambda = 1.0 / np.sqrt(inv_lamb_sq)
    k_term = np.sqrt((1.0 / lambda_0**2) - inv_lamb_c_sq + 0j)

    with np.errstate(divide="ignore", invalid="ignore"):
        mu_r  = (1.0 + Gamma) / ((1.0 - Gamma) * Lambda * k_term)
        eps_r = (lambda_0**2 / (mu_r + 1e-300)) * (inv_lamb_c_sq + inv_lamb_sq)

    return eps_r, mu_r


# ═════════════════════════════════════════════════════════════════════════════
#  SOLT calibration
# ═════════════════════════════════════════════════════════════════════════════

class _SOLTCal:
    """
    One-port 3-term error model solved from SOL standards.

    mode='ideal'  — assumes Short=-1, Open=+1, Load=0 (closed form from
                    calibration_final.py)
    mode='actual' — full per-frequency AE=B solve with known standard arrays
                    (also from calibration_final.py)
    """

    def __init__(
        self,
        freqs:      np.ndarray,
        S11m_short: np.ndarray,
        S11m_open:  np.ndarray,
        S11m_load:  np.ndarray,
        delay_m:    float,
        mode:       str = "ideal",
        S11a_short: Optional[np.ndarray] = None,
        S11a_open:  Optional[np.ndarray] = None,
        S11a_load:  Optional[np.ndarray] = None,
    ) -> None:
        self.freqs   = freqs
        self.delay_m = delay_m
        Nf           = len(freqs)

        if mode == "ideal":
            # Closed-form: direct from calibration_final.py
            e00    = S11m_load.copy()
            holder = (e00 - S11m_short) / (S11m_open - e00)
            e11    = (1 - holder) / (holder + 1)
            e10e01 = (e00 - S11m_short) * (1 + e11)
            Delta  = e00 * e11 - e10e01

        elif mode == "actual":
            if any(a is None for a in (S11a_short, S11a_open, S11a_load)):
                raise ValueError("mode='actual' requires S11a_short/open/load")
            e00   = np.zeros(Nf, dtype=complex)
            e11   = np.zeros(Nf, dtype=complex)
            Delta = np.zeros(Nf, dtype=complex)
            for i in range(Nf):
                # Row layout: [1, Gamma_std*Gamma_meas, -Gamma_std]
                A = np.array([
                    [1, S11a_short[i] * S11m_short[i], -S11a_short[i]],
                    [1, S11a_open[i]  * S11m_open[i],  -S11a_open[i] ],
                    [1, S11a_load[i]  * S11m_load[i],  -S11a_load[i] ],
                ])
                b               = np.array([S11m_short[i], S11m_open[i], S11m_load[i]])
                x               = np.linalg.solve(A, b)
                e00[i], e11[i], Delta[i] = x
        else:
            raise ValueError(f"Unknown calibration mode: '{mode}'")

        self.e00   = e00
        self.e11   = e11
        self.Delta = Delta

    # ── Apply correction ──────────────────────────────────────────────────────

    def correct(self, S11m: np.ndarray) -> np.ndarray:
        return (S11m - self.e00) / (self.e11 * S11m - self.Delta)

    def deembed(self, S11c: np.ndarray) -> np.ndarray:
        """Remove round-trip phase of coaxial delay line."""
        beta = 2.0 * np.pi * self.freqs / C_LIGHT
        return S11c * np.exp(2j * beta * self.delay_m)

    def correct_and_deembed(self, S11m: np.ndarray) -> np.ndarray:
        return self.deembed(self.correct(S11m))

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self, path: str) -> None:
        np.savez(path,
                 freqs   = self.freqs,
                 delay_m = np.array(self.delay_m),
                 e00     = self.e00,
                 e11     = self.e11,
                 Delta   = self.Delta)
        log.info("Calibration saved → %s", path)

    @classmethod
    def load(cls, path: str) -> "_SOLTCal":
        d   = np.load(path)
        obj = object.__new__(cls)
        obj.freqs   = d["freqs"]
        obj.delay_m = float(d["delay_m"].item())
        obj.e00     = d["e00"]
        obj.e11     = d["e11"]
        obj.Delta   = d["Delta"]
        log.info("Calibration loaded ← %s", path)
        return obj


# ═════════════════════════════════════════════════════════════════════════════
#  VNA plugin — architecture mirrors cyBot_Plugin.py exactly
# ═════════════════════════════════════════════════════════════════════════════

class motion_controller_plugin(MotionControllerPlugin):
    """
    VNA plugin for Scan_Controller_Probe_Main.

    The class is named motion_controller_plugin (lowercase) to match the
    naming convention used by cyBot_Plugin.py and the plugin loader.
    """

    def __init__(self):
        super().__init__()

        # ── UI settings  (same API as cyBot_Plugin) ───────────────────────────
        self.address       = PluginSettingString ("IP Address",    "192.168.1.2")
        self.port          = PluginSettingInteger("Port",          2888)
        self.timeout       = PluginSettingInteger("Timeout (ms)",  10000)
        self.f_start_set   = PluginSettingString ("f_start (Hz)",  "2400000000")
        self.f_stop_set    = PluginSettingString ("f_stop  (Hz)",  "2600000000")
        self.n_points_set  = PluginSettingInteger("N Points",      201)
        self.delay_mm_set  = PluginSettingInteger("Delay (mm)",    10)
        self.sample_mm_set = PluginSettingInteger("Sample L (mm)", 5)

        for s in (self.address, self.port, self.timeout,
                  self.f_start_set, self.f_stop_set, self.n_points_set,
                  self.delay_mm_set, self.sample_mm_set):
            self.add_setting_pre_connect(s)

        # ── Socket  (self.vna mirrors self.cybot in cyBot_Plugin) ─────────────
        self.vna              = None
        self.read_thread      = None
        self.read_thread_cond = False

        # ── Events  (same names / usage as cyBot_Plugin) ─────────────────────
        self.ok_received    = threading.Event()
        self.sweep_finished = threading.Event()

        # ── Recv buffer  (same pattern as cybot recv_buf) ─────────────────────
        self._recv_buf    : str         = ""
        self._sweep_freqs : list[float] = []
        self._sweep_re    : list[float] = []
        self._sweep_im    : list[float] = []

        # ── Calibration / NRW ─────────────────────────────────────────────────
        self._cal   : Optional[_SOLTCal]   = None
        self._freqs : Optional[np.ndarray] = None

        # ── Pending sweep result (set in scan_trigger_and_wait) ───────────────
        self._last_S11_raw: Optional[np.ndarray] = None

        # ── HDF5 handles (set in scan_begin) ─────────────────────────────────
        self._h5        : Optional[h5py.File] = None
        self._ds_raw    = None
        self._ds_cal    = None
        self._ds_eps    = None
        self._ds_mu     = None
        self._scan_nx   = 1
        self._scan_ny   = 1
        self._point_idx = 0

    # ═════════════════════════════════════════════════════════════════════════
    #  Connection  (mirrors cybot.connect)
    # ═════════════════════════════════════════════════════════════════════════

    def connect(self):
        import socket as _socket
        try:
            self.vna = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
            self.vna.settimeout(self.timeout.value / 1000)
            self.vna.connect((self.address.value, self.port.value))
            log.info("VNA connected  %s:%d", self.address.value, self.port.value)

            # Start background reader  (daemon=True, same as cybot)
            self.read_thread_cond = True
            self.read_thread = threading.Thread(
                target=self.read_thread_interrupt,
                daemon=True,
                name="vna-rx",
            )
            self.read_thread.start()

            # Configure frequency sweep
            self.send_command(
                f"CONFIG {int(self.f_start_set.value)} "
                f"{int(self.f_stop_set.value)} "
                f"{self.n_points_set.value}"
            )
            if not self.ok_received.wait(timeout=5.0):
                raise RuntimeError("VNA did not ACK CONFIG")
            self.ok_received.clear()

            # Warm-up sweep so PLL settles before calibration
            self._do_sweep()
            log.info("VNA ready  %.3f–%.3f GHz  %d pts",
                     int(self.f_start_set.value) / 1e9,
                     int(self.f_stop_set.value)  / 1e9,
                     self.n_points_set.value)

        except Exception as exc:
            log.error("VNA connect failed: %s", exc)
            self.vna = None

    def disconnect(self):
        self.read_thread_cond = False
        if self.read_thread:
            self.read_thread.join(timeout=2.0)
        if self.vna:
            try:
                self.vna.close()
            except Exception:
                pass
            log.info("VNA disconnected")

    # ═════════════════════════════════════════════════════════════════════════
    #  Background read thread  (mirrors cybot.read_thread_interrupt exactly)
    # ═════════════════════════════════════════════════════════════════════════

    def read_thread_interrupt(self):
        """
        Daemon thread.  Reads the socket, accumulates characters into
        self._recv_buf, splits on '\\n', dispatches each line to _parse_line.
        Identical structure to cyBot_Plugin.read_thread_interrupt.
        """
        import socket as _socket
        self._recv_buf = ""
        while self.read_thread_cond:
            try:
                data = self.vna.recv(4096)
                if not data:
                    break

                self._recv_buf += data.decode("utf-8", errors="ignore")

                while "\n" in self._recv_buf:
                    line, self._recv_buf = self._recv_buf.split("\n", 1)
                    decoded = line.strip()
                    if decoded:
                        self._parse_line(decoded)

            except _socket.timeout:
                continue
            except Exception:
                break

    def _parse_line(self, decoded: str):
        """
        Dispatch on line content.
        Mirrors cybot._parse_line — each protocol keyword sets an Event
        or appends to the sweep accumulator lists.
        """
        # Firmware ACK
        if decoded == "OK":
            self.ok_received.set()
            return

        # Sweep header: "SWEEP_START <Nf>"
        if decoded.startswith("SWEEP_START"):
            self._sweep_freqs.clear()
            self._sweep_re.clear()
            self._sweep_im.clear()
            return

        # One data line: "F <freq_hz> <re_S11> <im_S11>"
        if decoded.startswith("F "):
            try:
                _, freq, re, im = decoded.split()
                self._sweep_freqs.append(float(freq))
                self._sweep_re.append(float(re))
                self._sweep_im.append(float(im))
            except ValueError:
                log.warning("bad sweep line: %s", decoded)
            return

        # Sweep footer — signal waiting thread
        if decoded == "SWEEP_END":
            self.sweep_finished.set()
            return

    # ═════════════════════════════════════════════════════════════════════════
    #  Command sender  (mirrors cybot.send_gcode_command)
    # ═════════════════════════════════════════════════════════════════════════

    def send_command(self, command: str):
        if self.vna:
            self.vna.send((command + "\n").encode("utf-8"))
            log.debug("TX: %s", command)

    # ═════════════════════════════════════════════════════════════════════════
    #  Sweep helper
    # ═════════════════════════════════════════════════════════════════════════

    def _do_sweep(self) -> tuple[np.ndarray, np.ndarray]:
        """Trigger one sweep, block on sweep_finished Event, return (freqs, S11)."""
        self.sweep_finished.clear()
        self.send_command("SWEEP")

        timeout_s = self.timeout.value / 1000
        if not self.sweep_finished.wait(timeout=timeout_s):
            raise TimeoutError("VNA sweep timed out")

        freqs = np.array(self._sweep_freqs, dtype=np.float64)
        S11   = (np.array(self._sweep_re, dtype=np.float64)
                 + 1j * np.array(self._sweep_im, dtype=np.float64))
        return freqs, S11

    # ═════════════════════════════════════════════════════════════════════════
    #  Interactive SOL calibration
    # ═════════════════════════════════════════════════════════════════════════

    def _run_sol_calibration(self) -> None:
        """
        Prompt the operator to connect each standard then sweep.
        Same interactive console pattern as the cybot nav() / show_radar()
        workflow — operator presses Enter in the terminal between standards.
        """
        print("\n[VNA] ── SOL Calibration ──────────────────────────────")
        results: dict[str, np.ndarray] = {}
        freqs: Optional[np.ndarray]    = None

        for name in ("SHORT", "OPEN", "LOAD"):
            input(f"  Attach {name} standard and press Enter...")
            f, S11      = self._do_sweep()
            results[name] = S11
            freqs         = f
            print(f"  {name} swept  ({len(f)} points)")

        self._freqs = freqs
        self._cal   = _SOLTCal(
            freqs      = freqs,
            S11m_short = results["SHORT"],
            S11m_open  = results["OPEN"],
            S11m_load  = results["LOAD"],
            delay_m    = self.delay_mm_set.value / 1000.0,
            mode       = "ideal",
        )
        input("  Remove standard, attach DUT fixture, and press Enter...")
        print("[VNA] Calibration complete.\n")

    # ═════════════════════════════════════════════════════════════════════════
    #  MotionControllerPlugin scan interface
    # ═════════════════════════════════════════════════════════════════════════

    def scan_begin(self):
        """Called once before the raster. Runs SOL calibration and sets up HDF5."""
        super().scan_begin()
        self._point_idx = 0
        self._run_sol_calibration()

        # Locate the HDF5 file the scan controller already opened
        h5 = self._find_h5_file()
        if h5 is not None:
            self._setup_hdf5(h5)
        else:
            log.warning("scan_begin: HDF5 file not found on base class — "
                        "datasets will be created on first measurement instead")

    def scan_end(self):
        super().scan_end()
        log.info("VNA scan finished  %d points written", self._point_idx)

    def scan_trigger_and_wait(self, i, l):
        """
        Trigger one VNA sweep and wait for completion.
        Stores the raw result for scan_read_measurement to pick up.
        """
        super().scan_trigger_and_wait(i, l)
        try:
            _, S11_raw          = self._do_sweep()
            self._last_S11_raw  = S11_raw
        except TimeoutError as exc:
            log.error("sweep timeout at point %d: %s", self._point_idx, exc)
            Nf                  = len(self._freqs) if self._freqs is not None else 0
            self._last_S11_raw  = np.zeros(Nf, dtype=complex)

    def scan_read_measurement(self, i, l):
        """
        Apply SOLT + de-embedding + NRW and write to HDF5.
        Returns a dict the scan controller can use for its own logging.
        """
        super().scan_read_measurement(i, l)

        S11_raw = self._last_S11_raw
        S11_cal = self._cal.correct_and_deembed(S11_raw)

        # NRW — use |S21| ≈ sqrt(1 - |S11|²) when only one port is measured.
        # Swap in a real S21 array here if a two-port fixture is available.
        S21 = np.sqrt(np.maximum(1.0 - np.abs(S11_cal)**2, 0.0)).astype(complex)
        L   = self.sample_mm_set.value / 1000.0
        eps_r, mu_r = _nrw(S11_cal, S21, self._freqs, L)

        # Write to pre-allocated HDF5 datasets
        if self._h5 is not None:
            ix = self._point_idx // self._scan_ny
            iy = self._point_idx  % self._scan_ny
            # Lazily create datasets if scan_begin couldn't find the file
            if self._ds_raw is None:
                self._setup_hdf5(self._h5)
            self._ds_raw[ix, iy, :] = S11_raw
            self._ds_cal[ix, iy, :] = S11_cal
            self._ds_eps[ix, iy, :] = eps_r
            self._ds_mu [ix, iy, :] = mu_r
            self._h5.flush()

        self._point_idx += 1

        return {
            "S11_raw": S11_raw,
            "S11_cal": S11_cal,
            "eps_r":   eps_r,
            "mu_r":    mu_r,
        }

    # ─────────────────────────────────────────────────────────────────────────
    #  HDF5 helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _find_h5_file(self) -> Optional[h5py.File]:
        """
        Look for the open HDF5 file on the base class.
        Scan_Controller_Probe_Main stores it under one of these names.
        """
        for attr in ("_h5_file", "h5_file", "_hdf5", "hdf5", "data_file"):
            if hasattr(self, attr):
                val = getattr(self, attr)
                if isinstance(val, h5py.File):
                    return val
        return None

    def _setup_hdf5(self, h5: h5py.File) -> None:
        self._h5 = h5
        Nf = len(self._freqs)

        # Try to read Nx/Ny from the base class scan parameters dict
        try:
            self._scan_nx = int(self._scan_params["nx"])
            self._scan_ny = int(self._scan_params["ny"])
        except (AttributeError, KeyError, TypeError):
            self._scan_nx = 1
            self._scan_ny = 1

        Nx, Ny = self._scan_nx, self._scan_ny

        grp = h5.require_group("/scan/vna")
        grp.attrs["f_start_hz"]      = float(self.f_start_set.value)
        grp.attrs["f_stop_hz"]       = float(self.f_stop_set.value)
        grp.attrs["n_points"]        = int(self.n_points_set.value)
        grp.attrs["delay_m"]         = self.delay_mm_set.value  / 1000.0
        grp.attrs["sample_length_m"] = self.sample_mm_set.value / 1000.0

        grp.create_dataset("freqs", data=self._freqs, compression="gzip")

        cal = grp.require_group("cal")
        cal.create_dataset("e00",   data=self._cal.e00,   compression="gzip")
        cal.create_dataset("e11",   data=self._cal.e11,   compression="gzip")
        cal.create_dataset("Delta", data=self._cal.Delta, compression="gzip")

        kw = dict(dtype=np.complex128, compression="gzip", chunks=(1, 1, Nf))
        self._ds_raw = grp.create_dataset("S11_raw", shape=(Nx, Ny, Nf), **kw)
        self._ds_cal = grp.create_dataset("S11_cal", shape=(Nx, Ny, Nf), **kw)
        self._ds_eps = grp.create_dataset("eps_r",   shape=(Nx, Ny, Nf), **kw)
        self._ds_mu  = grp.create_dataset("mu_r",    shape=(Nx, Ny, Nf), **kw)

        log.info("HDF5 datasets created  %d × %d × %d", Nx, Ny, Nf)

    # ─────────────────────────────────────────────────────────────────────────
    #  Standard MotionControllerPlugin stubs  (same as cyBot_Plugin)
    # ─────────────────────────────────────────────────────────────────────────

    def get_channel_names(self):              return super().get_channel_names()
    def get_xaxis_coords(self):               return super().get_xaxis_coords()
    def get_xaxis_units(self):                return super().get_xaxis_units()
    def get_yaxis_units(self):                return super().get_yaxis_units()
    def get_axis_display_names(self):         pass
    def get_axis_units(self):                 pass
    def set_velocity(self, velocities=None):  pass
    def set_acceleration(self, accels=None):  pass
    def move_relative(self, p):               pass
    def get_current_positions(self):          pass
    def is_moving(self, axis=None):           pass
    def get_endstop_minimums(self):           pass
    def get_endstop_maximums(self):           pass
    def set_config(self, a, b, c):            pass
    def emergency_stop(self):                 pass
    def move_absolute(self, move_dist):       pass
    def home(self, axes=None):                pass
    def show_radar(self):
        pass