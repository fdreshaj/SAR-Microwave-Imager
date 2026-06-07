# gui/ui_modern.py
"""
Modern replacement for Ui_MainWindow.
Exposes the same widget names that test_scanner_gui.py references so it
is a drop-in swap — no changes needed in the logic file.

Widget name compatibility map (old → still present here):
  config_layout               QFormLayout  (sidebar plugin config panel)
  plot_config_wid             QFormLayout  (sidebar plot controls)
  x_plus_button / x_minus_button / y_plus_button / y_minus_button
  z_plus_button / z_minus_button
  xy_move_amount / z_move_amount  QDoubleSpinBox
  x_axis_slider / y_axis_slider / z_axis_slider  QAxisPositionSlider
  configure_motion_button / configure_probe_button
  configure_pattern_button / configure_file_button  QPushButton (checkable)
  start_scan_button           QPushButton
  scan_progress_bar           QProgressBar
  time_elapsed_box            QLineEdit (read-only)
  time_remaining_box          QLineEdit (read-only)
  motion_connected_checkbox   QCheckBox (display-only)
  checkBox                    QCheckBox (display-only, probe)
"""

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont, QColor, QPalette
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QFormLayout,
    QFrame, QLabel, QPushButton, QDoubleSpinBox,
    QProgressBar, QLineEdit, QCheckBox, QSizePolicy,
    QScrollArea, QSplitter, QStackedWidget, QApplication,
    QGridLayout,
)
from gui.qt_util import QAxisPositionSlider


# ---------------------------------------------------------------------------
# Design tokens — Dark Industrial theme
# ---------------------------------------------------------------------------
_DARK = {
    "bg0":      "#0d0d0d",
    "bg1":      "#141414",
    "bg2":      "#1a1a1a",
    "bg3":      "#222222",
    "border":   "#2a2a2a",
    "border2":  "#333333",
    "text":     "#e8e8e8",
    "muted":    "#666666",
    "dim":      "#444444",
    "accent":   "#f0f0f0",
    "accent2":  "#c8c8c8",
    "ok":       "#44aa88",
    "warn":     "#cc8844",
    "err":      "#cc4444",
    "font":     "ui-monospace, 'JetBrains Mono', 'Fira Code', Consolas, monospace",
}

_CYBER = {
    "bg0":      "#050508",
    "bg1":      "#080b10",
    "bg2":      "#0c1018",
    "bg3":      "#101520",
    "border":   "#0f1a24",
    "border2":  "#162030",
    "border3":  "#1e2d40",
    "text":     "#c8dde8",
    "muted":    "#3a5568",
    "dim":      "#2a3d50",
    "accent":   "#00d4ff",
    "accent2":  "#00a8cc",
    "ok":       "#00ff88",
    "warn":     "#ffaa00",
    "err":      "#ff3355",
    "font":     "ui-monospace, 'JetBrains Mono', 'Fira Code', Consolas, monospace",
}

# Change this to switch themes: "dark" or "cyber"
THEME = "dark"
T = _DARK if THEME == "dark" else _CYBER


# ---------------------------------------------------------------------------
# Stylesheet helpers
# ---------------------------------------------------------------------------
def _ss_window():
    return f"""
        QMainWindow, QWidget#central {{
            background: {T['bg0']};
            color: {T['text']};
        }}
    """


def _ss_sidebar():
    return f"""
        QWidget#sidebar {{
            background: {T['bg1']};
            border-right: 1px solid {T['border2']};
        }}
    """


def _ss_section_header():
    return f"""
        QLabel {{
            color: {T['muted']};
            font-size: 9px;
            letter-spacing: 2px;
            text-transform: uppercase;
            padding: 8px 14px 4px 14px;
            background: {T['bg1']};
        }}
    """


def _ss_field_value():
    return f"""
        QLineEdit, QDoubleSpinBox {{
            background: {T['bg0']};
            color: {T['accent2']};
            border: 1px solid {T['border']};
            padding: 4px 7px;
            font-family: {T['font']};
            font-size: 11px;
            selection-background-color: {T['border2']};
        }}
        QLineEdit:focus, QDoubleSpinBox:focus {{
            border: 1px solid {T['border2']};
        }}
        QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
            width: 14px;
            background: {T['bg2']};
            border: none;
        }}
    """


def _ss_btn(style="normal"):
    base = f"""
        QPushButton {{
            background: transparent;
            color: {T['muted']};
            border: 1px solid {T['border']};
            padding: 6px 10px;
            font-family: {T['font']};
            font-size: 10px;
            letter-spacing: 1px;
            text-transform: uppercase;
        }}
        QPushButton:hover {{
            border: 1px solid {T['accent2']};
            color: {T['accent']};
        }}
        QPushButton:checked {{
            border: 1px solid {T['accent2']};
            color: {T['accent']};
            background: {T['bg2']};
        }}
    """
    if style == "primary":
        return base + f"""
        QPushButton {{
            border: 1px solid {T['accent2']};
            color: {T['accent']};
        }}
        QPushButton:hover {{
            background: {T['bg2']};
        }}
        """
    if style == "go":
        col = T['ok']
        return base + f"""
        QPushButton {{
            border: 1px solid {col};
            color: {col};
        }}
        QPushButton:hover {{
            background: rgba(68,170,136,0.1);
        }}
        """
    if style == "danger":
        col = T['err']
        return base + f"""
        QPushButton {{
            border: 1px solid #441818;
            color: {col};
        }}
        QPushButton:hover {{
            background: rgba(204,68,68,0.1);
        }}
        """
    return base


def _ss_progress():
    accent = T['accent2'] if THEME == "dark" else T['accent']
    glow = f"box-shadow: 0 0 6px {accent};" if THEME == "cyber" else ""
    return f"""
        QProgressBar {{
            background: {T['border']};
            border: none;
            height: 2px;
            text-align: center;
            color: transparent;
        }}
        QProgressBar::chunk {{
            background: {accent};
        }}
    """


def _ss_slider():
    return f"""
        QSlider::groove:horizontal {{
            background: {T['border']};
            height: 2px;
        }}
        QSlider::handle:horizontal {{
            background: {T['accent2']};
            width: 8px; height: 8px;
            margin: -3px 0;
            border-radius: 4px;
        }}
        QSlider::groove:vertical {{
            background: {T['border']};
            width: 2px;
        }}
        QSlider::handle:vertical {{
            background: {T['accent2']};
            width: 8px; height: 8px;
            margin: 0 -3px;
            border-radius: 4px;
        }}
    """


def _ss_checkbox():
    return f"""
        QCheckBox {{
            color: {T['muted']};
            font-size: 10px;
            spacing: 6px;
        }}
        QCheckBox::indicator {{
            width: 10px; height: 10px;
            border: 1px solid {T['border2']};
            background: {T['bg0']};
        }}
        QCheckBox::indicator:checked {{
            background: {T['ok']};
            border: 1px solid {T['ok']};
        }}
    """


def _ss_scroll():
    return f"""
        QScrollArea {{ border: none; background: transparent; }}
        QScrollBar:vertical {{
            background: {T['bg1']};
            width: 4px;
            border: none;
        }}
        QScrollBar::handle:vertical {{
            background: {T['border2']};
            border-radius: 2px;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
    """


def _ss_topbar():
    return f"""
        QWidget#topbar {{
            background: {T['bg1']};
            border-bottom: 1px solid {T['border2']};
        }}
        QLabel#logo {{
            color: {T['accent']};
            font-size: 12px;
            font-weight: bold;
            letter-spacing: 3px;
        }}
        QLabel#tb_key {{
            color: {T['muted']};
            font-size: 9px;
            letter-spacing: 2px;
        }}
        QLabel#tb_val {{
            color: {T['accent2']};
            font-size: 10px;
        }}
    """


def _ss_statusbar():
    return f"""
        QWidget#statusbar_w {{
            background: {T['bg1']};
            border-top: 1px solid {T['border2']};
        }}
        QLabel {{
            color: {T['muted']};
            font-size: 9px;
            letter-spacing: 1px;
        }}
        QLabel#sb_val {{
            color: {T['accent2']};
        }}
    """


def _ss_main_area():
    return f"""
        QWidget#main_area {{
            background: {T['bg0']};
        }}
    """


def _ss_plugin_row():
    return f"""
        QWidget#plugin_row {{
            background: {T['bg2']};
            border: 1px solid {T['border']};
        }}
        QLabel#plug_name {{
            color: {T['accent2']};
            font-size: 11px;
        }}
        QLabel#plug_status {{
            font-size: 9px;
            letter-spacing: 1px;
        }}
    """


# ---------------------------------------------------------------------------
# Small reusable widgets
# ---------------------------------------------------------------------------
class SectionHeader(QLabel):
    def __init__(self, text, parent=None):
        super().__init__(text.upper(), parent)
        self.setStyleSheet(f"""
            color: {T['muted']};
            font-size: 9px;
            letter-spacing: 2px;
            padding: 10px 14px 3px 14px;
            background: transparent;
        """)
        self.setFont(QFont(T['font'].split(",")[0].strip().strip("'"), 8))


class HSep(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.HLine)
        self.setStyleSheet(f"background: {T['border']}; border: none; max-height: 1px;")


class VSep(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.VLine)
        self.setStyleSheet(f"background: {T['border2']}; border: none; max-width: 1px;")


class StatusDot(QLabel):
    def __init__(self, color=None, parent=None):
        super().__init__("●", parent)
        c = color or T['ok']
        self.setStyleSheet(f"color: {c}; font-size: 7px; padding: 0 2px;")
        self.setFixedWidth(14)


class PluginRow(QWidget):
    """A styled row showing plugin name + status with a colored left bar."""
    def __init__(self, name, status="—", color=None, parent=None):
        super().__init__(parent)
        self.setObjectName("plugin_row")
        self._color = color or T['ok']
        self.setFixedHeight(34)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # colored left bar
        bar = QFrame(self)
        bar.setFixedWidth(3)
        bar.setStyleSheet(f"background: {self._color}; border: none;")
        outer.addWidget(bar)

        inner = QHBoxLayout()
        inner.setContentsMargins(10, 0, 10, 0)
        inner.setSpacing(0)

        self.name_lbl = QLabel(name)
        self.name_lbl.setObjectName("plug_name")
        self.name_lbl.setStyleSheet(f"color: {T['accent2']}; font-size: 11px;")
        inner.addWidget(self.name_lbl)
        inner.addStretch()

        self.status_lbl = QLabel(status.upper())
        self.status_lbl.setObjectName("plug_status")
        self.status_lbl.setStyleSheet(f"color: {self._color}; font-size: 9px; letter-spacing: 1px;")
        inner.addWidget(self.status_lbl)

        inner_w = QWidget()
        inner_w.setLayout(inner)
        inner_w.setStyleSheet(f"background: {T['bg2']}; border: 1px solid {T['border']};")
        outer.addWidget(inner_w)

    def set_status(self, status, color=None):
        c = color or self._color
        self.status_lbl.setText(status.upper())
        self.status_lbl.setStyleSheet(f"color: {c}; font-size: 9px; letter-spacing: 1px;")


def _make_label(text, role="key"):
    lbl = QLabel(text.upper())
    if role == "key":
        lbl.setStyleSheet(f"color: {T['muted']}; font-size: 9px; letter-spacing: 1px;")
    else:
        lbl.setStyleSheet(f"color: {T['accent2']}; font-size: 10px;")
    return lbl


def _mono_btn(text, style="normal"):
    btn = QPushButton(text)
    btn.setStyleSheet(_ss_btn(style))
    btn.setFont(QFont(T['font'].split(",")[0].strip().strip("'"), 9))
    return btn


def _field_spinbox(decimals=5, val=10.0, mini=-1e15, maxi=1e15):
    sb = QDoubleSpinBox()
    sb.setDecimals(decimals)
    sb.setMinimum(mini)
    sb.setMaximum(maxi)
    sb.setValue(val)
    sb.setStyleSheet(_ss_field_value())
    sb.setFont(QFont(T['font'].split(",")[0].strip().strip("'"), 10))
    return sb


# ---------------------------------------------------------------------------
# The UI class — drop-in replacement for Ui_MainWindow
# ---------------------------------------------------------------------------
class Ui_MainWindow:
    """
    Exposes the same public widget attributes as the original Ui_MainWindow
    so test_scanner_gui.py requires zero changes.
    """

    def setupUi(self, MainWindow):
        MainWindow.setObjectName("MainWindow")
        MainWindow.setWindowTitle("CNDE — SAR Scanner")
        MainWindow.resize(1280, 760)
        MainWindow.setMinimumSize(QSize(900, 600))

        mono = QFont(T['font'].split(",")[0].strip().strip("'"), 10)

        # ── central widget ──────────────────────────────────────────────────
        central = QWidget()
        central.setObjectName("central")
        central.setStyleSheet(f"background: {T['bg0']}; color: {T['text']};")
        MainWindow.setCentralWidget(central)

        root_v = QVBoxLayout(central)
        root_v.setContentsMargins(0, 0, 0, 0)
        root_v.setSpacing(0)

        # ── top bar ─────────────────────────────────────────────────────────
        topbar = QWidget()
        topbar.setObjectName("topbar")
        topbar.setFixedHeight(42)
        topbar.setStyleSheet(f"""
            background: {T['bg1']};
            border-bottom: 1px solid {T['border2']};
        """)
        tb_h = QHBoxLayout(topbar)
        tb_h.setContentsMargins(14, 0, 14, 0)
        tb_h.setSpacing(14)

        logo = QLabel("◈  CNDE / SAR")
        logo.setObjectName("logo")
        logo.setStyleSheet(f"color: {T['accent']}; font-size: 12px; font-weight: bold; letter-spacing: 3px;")
        logo.setFont(mono)
        tb_h.addWidget(logo)

        sep1 = VSep(); sep1.setFixedHeight(18)
        tb_h.addWidget(sep1)

        self._tb_session_val = QLabel("—")
        self._tb_session_val.setStyleSheet(f"color: {T['accent2']}; font-size: 10px;")
        self._tb_session_val.setFont(mono)
        tb_h.addWidget(_make_label("Session"))
        tb_h.addWidget(self._tb_session_val)

        sep2 = VSep(); sep2.setFixedHeight(18)
        tb_h.addWidget(sep2)

        self._tb_file_val = QLabel("—")
        self._tb_file_val.setStyleSheet(f"color: {T['accent2']}; font-size: 10px;")
        self._tb_file_val.setFont(mono)
        tb_h.addWidget(_make_label("HDF5"))
        tb_h.addWidget(self._tb_file_val)

        tb_h.addStretch()

        # status dots
        self._dot_motion = StatusDot(T['dim'])
        self._dot_probe  = StatusDot(T['dim'])
        self._dot_file   = StatusDot(T['dim'])
        for dot, key in [(self._dot_motion, "Motion"),
                         (self._dot_probe,  "VNA"),
                         (self._dot_file,   "File")]:
            tb_h.addWidget(dot)
            tb_h.addWidget(_make_label(key))
            s = VSep(); s.setFixedHeight(14)
            tb_h.addWidget(s)

        self._mode_label = QLabel("IDLE")
        self._mode_label.setStyleSheet(f"""
            color: {T['muted']}; font-size: 10px; letter-spacing: 2px;
            border: 1px solid {T['border2']}; padding: 2px 8px;
        """)
        self._mode_label.setFont(mono)
        tb_h.addWidget(self._mode_label)

        root_v.addWidget(topbar)

        # ── body (sidebar + main) ────────────────────────────────────────────
        body = QWidget()
        body_h = QHBoxLayout(body)
        body_h.setContentsMargins(0, 0, 0, 0)
        body_h.setSpacing(0)
        root_v.addWidget(body, stretch=1)

        # ── sidebar ──────────────────────────────────────────────────────────
        sidebar_scroll = QScrollArea()
        sidebar_scroll.setObjectName("sidebar_scroll")
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setFixedWidth(270)
        sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sidebar_scroll.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                border-right: 1px solid {T['border2']};
                background: {T['bg1']};
            }}
            QScrollBar:vertical {{
                background: {T['bg1']};
                width: 4px; border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {T['border2']};
                border-radius: 2px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)

        sidebar_inner = QWidget()
        sidebar_inner.setStyleSheet(f"background: {T['bg1']};")
        sidebar_v = QVBoxLayout(sidebar_inner)
        sidebar_v.setContentsMargins(0, 0, 0, 0)
        sidebar_v.setSpacing(0)

        sidebar_scroll.setWidget(sidebar_inner)
        body_h.addWidget(sidebar_scroll)

        # ── SECTION: Plugins ────────────────────────────────────────────────
        sidebar_v.addWidget(SectionHeader("Plugins"))
        sidebar_v.addWidget(HSep())

        plug_w = QWidget()
        plug_w.setStyleSheet(f"background: {T['bg1']};")
        plug_v = QVBoxLayout(plug_w)
        plug_v.setContentsMargins(10, 6, 10, 6)
        plug_v.setSpacing(4)

        self._plug_motion  = PluginRow("Motion Controller", "—", T['dim'])
        self._plug_probe   = PluginRow("VNA Probe",         "—", T['dim'])
        self._plug_pattern = PluginRow("Scan Pattern",      "—", T['dim'])
        self._plug_file    = PluginRow("File Handler",      "—", T['dim'])
        for row in [self._plug_motion, self._plug_probe,
                    self._plug_pattern, self._plug_file]:
            plug_v.addWidget(row)

        # Configure buttons (checkable, same as original)
        btn_grid = QGridLayout()
        btn_grid.setSpacing(4)
        btn_grid.setContentsMargins(0, 4, 0, 0)

        self.configure_motion_button  = _mono_btn("Motion",  "primary")
        self.configure_probe_button   = _mono_btn("Probe",   "primary")
        self.configure_pattern_button = _mono_btn("Pattern", "primary")
        self.configure_file_button    = _mono_btn("File",    "primary")
        for btn in [self.configure_motion_button, self.configure_probe_button,
                    self.configure_pattern_button, self.configure_file_button]:
            btn.setCheckable(True)

        btn_grid.addWidget(self.configure_motion_button,  0, 0)
        btn_grid.addWidget(self.configure_probe_button,   0, 1)
        btn_grid.addWidget(self.configure_pattern_button, 1, 0)
        btn_grid.addWidget(self.configure_file_button,    1, 1)
        plug_v.addLayout(btn_grid)

        # hidden checkboxes (logic reads these)
        self.motion_connected_checkbox = QCheckBox("Connected")
        self.motion_connected_checkbox.setCheckable(False)
        self.motion_connected_checkbox.hide()
        self.checkBox = QCheckBox("Connected")
        self.checkBox.setCheckable(False)
        self.checkBox.hide()
        plug_v.addWidget(self.motion_connected_checkbox)
        plug_v.addWidget(self.checkBox)

        sidebar_v.addWidget(plug_w)
        sidebar_v.addWidget(HSep())

        # ── SECTION: Axis Jog ───────────────────────────────────────────────
        sidebar_v.addWidget(SectionHeader("Axis Jog"))
        sidebar_v.addWidget(HSep())

        jog_w = QWidget()
        jog_w.setStyleSheet(f"background: {T['bg1']};")
        jog_v = QVBoxLayout(jog_w)
        jog_v.setContentsMargins(10, 6, 10, 8)
        jog_v.setSpacing(6)

        # XY step
        xy_row = QHBoxLayout()
        xy_row.setSpacing(4)
        xy_lbl = _make_label("XY Step")
        self.xy_move_amount = _field_spinbox(5, 10.0)
        self.xy_move_amount.setFixedHeight(28)
        xy_row.addWidget(xy_lbl)
        xy_row.addWidget(self.xy_move_amount)
        jog_v.addLayout(xy_row)

        # XY d-pad
        dpad = QGridLayout()
        dpad.setSpacing(3)
        self.y_plus_button  = _mono_btn("Y+")
        self.x_minus_button = _mono_btn("X−")
        self.x_plus_button  = _mono_btn("X+")
        self.y_minus_button = _mono_btn("Y−")
        for b in [self.y_plus_button, self.x_minus_button,
                  self.x_plus_button, self.y_minus_button]:
            b.setFixedHeight(28)
        dpad.addWidget(self.y_plus_button,  0, 1)
        dpad.addWidget(self.x_minus_button, 1, 0)
        dpad.addWidget(self.x_plus_button,  1, 2)
        dpad.addWidget(self.y_minus_button, 2, 1)
        jog_v.addLayout(dpad)

        # Z step + buttons
        z_row = QHBoxLayout()
        z_row.setSpacing(4)
        z_lbl = _make_label("Z Step")
        self.z_move_amount = _field_spinbox(5, 10.0)
        self.z_move_amount.setFixedHeight(28)
        z_row.addWidget(z_lbl)
        z_row.addWidget(self.z_move_amount)
        jog_v.addLayout(z_row)

        z_btn_row = QHBoxLayout()
        z_btn_row.setSpacing(3)
        self.z_plus_button  = _mono_btn("Z+")
        self.z_minus_button = _mono_btn("Z−")
        for b in [self.z_plus_button, self.z_minus_button]:
            b.setFixedHeight(28)
        z_btn_row.addWidget(self.z_plus_button)
        z_btn_row.addWidget(self.z_minus_button)
        jog_v.addLayout(z_btn_row)

        # Axis position readouts (sliders hidden, still connected for logic)
        pos_grid = QGridLayout()
        pos_grid.setSpacing(3)
        for col, lbl in enumerate(["X", "Y", "Z"]):
            pos_grid.addWidget(_make_label(lbl), 0, col)
        self._x_pos = QLineEdit("0.000"); self._x_pos.setReadOnly(True)
        self._y_pos = QLineEdit("0.000"); self._y_pos.setReadOnly(True)
        self._z_pos = QLineEdit("0.000"); self._z_pos.setReadOnly(True)
        for col, w in enumerate([self._x_pos, self._y_pos, self._z_pos]):
            w.setFixedHeight(26)
            w.setStyleSheet(_ss_field_value())
            w.setFont(mono)
            pos_grid.addWidget(w, 1, col)
        jog_v.addLayout(pos_grid)

        # Hidden sliders — still connected to signals in scanner_qt
        self.x_axis_slider = QAxisPositionSlider()
        self.y_axis_slider = QAxisPositionSlider()
        self.z_axis_slider = QAxisPositionSlider()
        for sl in [self.x_axis_slider, self.y_axis_slider, self.z_axis_slider]:
            sl.setMinimum(-100); sl.setMaximum(100)
            sl.hide()
            jog_v.addWidget(sl)

        # Update display readouts when sliders change
        self.x_axis_slider.valueChanged.connect(
            lambda v: self._x_pos.setText(f"{self.x_axis_slider.current_value:.3f}"))
        self.y_axis_slider.valueChanged.connect(
            lambda v: self._y_pos.setText(f"{self.y_axis_slider.current_value:.3f}"))
        self.z_axis_slider.valueChanged.connect(
            lambda v: self._z_pos.setText(f"{self.z_axis_slider.current_value:.3f}"))

        sidebar_v.addWidget(jog_w)
        sidebar_v.addWidget(HSep())

        # ── SECTION: Plugin Config (dynamic) ────────────────────────────────
        sidebar_v.addWidget(SectionHeader("Configuration"))
        sidebar_v.addWidget(HSep())

        cfg_w = QWidget()
        cfg_w.setStyleSheet(f"background: {T['bg1']};")
        cfg_outer = QVBoxLayout(cfg_w)
        cfg_outer.setContentsMargins(10, 6, 10, 6)
        cfg_outer.setSpacing(0)

        self.config_layout = QFormLayout()
        self.config_layout.setSpacing(5)
        self.config_layout.setContentsMargins(0, 0, 0, 0)
        self.config_layout.setLabelAlignment(Qt.AlignLeft)
        cfg_outer.addLayout(self.config_layout)

        sidebar_v.addWidget(cfg_w)
        sidebar_v.addWidget(HSep())

        # ── SECTION: Plot Config (dynamic) ──────────────────────────────────
        sidebar_v.addWidget(SectionHeader("Plot Controls"))
        sidebar_v.addWidget(HSep())

        plot_cfg_w = QWidget()
        plot_cfg_w.setStyleSheet(f"background: {T['bg1']};")
        plot_cfg_outer = QVBoxLayout(plot_cfg_w)
        plot_cfg_outer.setContentsMargins(10, 6, 10, 6)
        plot_cfg_outer.setSpacing(0)

        self.plot_config_wid = QFormLayout()
        self.plot_config_wid.setSpacing(5)
        self.plot_config_wid.setContentsMargins(0, 0, 0, 0)
        self.plot_config_wid.setLabelAlignment(Qt.AlignLeft)
        plot_cfg_outer.addLayout(self.plot_config_wid)

        sidebar_v.addWidget(plot_cfg_w)

        sidebar_v.addStretch()

        # ── SECTION: Scan Controls (bottom of sidebar) ─────────────────────
        scan_ctrl = QWidget()
        scan_ctrl.setStyleSheet(f"background: {T['bg1']}; border-top: 1px solid {T['border2']};")
        scan_ctrl_v = QVBoxLayout(scan_ctrl)
        scan_ctrl_v.setContentsMargins(10, 10, 10, 10)
        scan_ctrl_v.setSpacing(6)

        self.start_scan_button = _mono_btn("▶  Start Scan", "go")
        self.start_scan_button.setFixedHeight(34)
        scan_ctrl_v.addWidget(self.start_scan_button)

        sidebar_v.addWidget(scan_ctrl)

        # ── main area ────────────────────────────────────────────────────────
        main_area = QWidget()
        main_area.setObjectName("main_area")
        main_area.setStyleSheet(f"background: {T['bg0']};")
        main_v = QVBoxLayout(main_area)
        main_v.setContentsMargins(0, 0, 0, 0)
        main_v.setSpacing(0)
        body_h.addWidget(main_area, stretch=1)

        # main header bar
        main_hdr = QWidget()
        main_hdr.setFixedHeight(38)
        main_hdr.setStyleSheet(f"background: {T['bg1']}; border-bottom: 1px solid {T['border2']};")
        mhdr_h = QHBoxLayout(main_hdr)
        mhdr_h.setContentsMargins(18, 0, 18, 0)
        mhdr_h.setSpacing(16)

        self._main_title = QLabel("S-PARAMETER MAP")
        self._main_title.setStyleSheet(f"color: {T['accent']}; font-size: 11px; letter-spacing: 2px;")
        self._main_title.setFont(mono)
        mhdr_h.addWidget(self._main_title)

        self._main_sub = QLabel("S11  ·  Magnitude  ·  —")
        self._main_sub.setStyleSheet(f"color: {T['muted']}; font-size: 10px;")
        self._main_sub.setFont(mono)
        mhdr_h.addWidget(self._main_sub)

        mhdr_h.addStretch()
        main_v.addWidget(main_hdr)

        # content area — this is where VisualizerWindow / plotter get embedded
        # test_scanner_gui calls setup_plotting_canvas which adds to this
        self.main_content = QWidget()
        self.main_content.setStyleSheet(f"background: {T['bg0']};")
        main_content_v = QVBoxLayout(self.main_content)
        main_content_v.setContentsMargins(0, 0, 0, 0)
        main_content_v.setSpacing(0)

        # xy_canvas exposed for compatibility (was used for display widget)
        self.xy_canvas = QWidget()
        self.xy_canvas.setStyleSheet(f"background: {T['bg0']};")
        main_content_v.addWidget(self.xy_canvas, stretch=1)

        main_v.addWidget(self.main_content, stretch=1)

        # ── progress strip ───────────────────────────────────────────────────
        prog_strip = QWidget()
        prog_strip.setFixedHeight(38)
        prog_strip.setStyleSheet(f"background: {T['bg1']}; border-top: 1px solid {T['border']};")
        prog_h = QHBoxLayout(prog_strip)
        prog_h.setContentsMargins(18, 0, 18, 0)
        prog_h.setSpacing(12)

        prog_lbl = _make_label("Progress")
        prog_h.addWidget(prog_lbl)

        self.scan_progress_bar = QProgressBar()
        self.scan_progress_bar.setValue(0)
        self.scan_progress_bar.setTextVisible(False)
        self.scan_progress_bar.setFixedHeight(2)
        self.scan_progress_bar.setStyleSheet(_ss_progress())
        prog_h.addWidget(self.scan_progress_bar, stretch=1)

        self._prog_pct = QLabel("0%")
        self._prog_pct.setStyleSheet(f"color: {T['accent2']}; font-size: 10px;")
        self._prog_pct.setFont(mono)
        self._prog_pct.setFixedWidth(36)
        prog_h.addWidget(self._prog_pct)

        prog_h.addWidget(VSep())

        prog_h.addWidget(_make_label("Elapsed"))
        self.time_elapsed_box = QLineEdit("—")
        self.time_elapsed_box.setReadOnly(True)
        self.time_elapsed_box.setFixedWidth(80)
        self.time_elapsed_box.setFixedHeight(22)
        self.time_elapsed_box.setStyleSheet(_ss_field_value())
        self.time_elapsed_box.setFont(mono)
        prog_h.addWidget(self.time_elapsed_box)

        prog_h.addWidget(_make_label("ETA"))
        self.time_remaining_box = QLineEdit("—")
        self.time_remaining_box.setReadOnly(True)
        self.time_remaining_box.setFixedWidth(80)
        self.time_remaining_box.setFixedHeight(22)
        self.time_remaining_box.setStyleSheet(_ss_field_value())
        self.time_remaining_box.setFont(mono)
        prog_h.addWidget(self.time_remaining_box)

        main_v.addWidget(prog_strip)

        # hook progress bar → percentage label
        self.scan_progress_bar.valueChanged.connect(
            lambda v: self._prog_pct.setText(f"{v}%"))

        # ── status bar ───────────────────────────────────────────────────────
        sb_w = QWidget()
        sb_w.setObjectName("statusbar_w")
        sb_w.setFixedHeight(26)
        sb_w.setStyleSheet(f"background: {T['bg1']}; border-top: 1px solid {T['border2']};")
        sb_h = QHBoxLayout(sb_w)
        sb_h.setContentsMargins(14, 0, 14, 0)
        sb_h.setSpacing(18)

        self._sb_motion = self._sb_item(sb_h, "Motion", "—")
        self._sb_vna    = self._sb_item(sb_h, "VNA",    "—")
        self._sb_points = self._sb_item(sb_h, "Points", "0")

        sb_h.addStretch()

        cr = QLabel("CNDE · Iowa State University · SAR Controller")
        cr.setStyleSheet(f"color: {T['dim']}; font-size: 9px; letter-spacing: 1px;")
        cr.setFont(mono)
        sb_h.addWidget(cr)

        root_v.addWidget(sb_w)

        # ── apply global stylesheet to all QPushButtons in config_layout ────
        central.setStyleSheet(central.styleSheet() + f"""
            QPushButton {{
                background: transparent;
                color: {T['muted']};
                border: 1px solid {T['border']};
                padding: 5px 8px;
                font-size: 10px;
                letter-spacing: 1px;
            }}
            QPushButton:hover {{
                border: 1px solid {T['accent2']};
                color: {T['accent']};
            }}
            QPushButton:checked {{
                border: 1px solid {T['accent2']};
                color: {T['accent']};
                background: {T['bg2']};
            }}
            QLineEdit {{
                background: {T['bg0']};
                color: {T['accent2']};
                border: 1px solid {T['border']};
                padding: 3px 6px;
                selection-background-color: {T['border2']};
            }}
            QDoubleSpinBox {{
                background: {T['bg0']};
                color: {T['accent2']};
                border: 1px solid {T['border']};
                padding: 3px 6px;
            }}
            QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
                width: 14px;
                background: {T['bg2']};
                border: none;
            }}
            QLabel {{
                color: {T['muted']};
                font-size: 10px;
            }}
            QCheckBox {{
                color: {T['muted']};
                font-size: 10px;
            }}
            QCheckBox::indicator {{
                width: 10px; height: 10px;
                border: 1px solid {T['border2']};
                background: {T['bg0']};
            }}
            QCheckBox::indicator:checked {{
                background: {T['ok']};
                border: 1px solid {T['ok']};
            }}
            QSlider::groove:horizontal {{
                background: {T['border']};
                height: 2px;
            }}
            QSlider::handle:horizontal {{
                background: {T['accent2']};
                width: 8px; height: 8px;
                margin: -3px 0;
                border-radius: 4px;
            }}
            QSlider::groove:vertical {{
                background: {T['border']};
                width: 2px;
            }}
            QSlider::handle:vertical {{
                background: {T['accent2']};
                width: 8px; height: 8px;
                margin: 0 -3px;
                border-radius: 4px;
            }}
            QProgressBar {{
                background: {T['border']};
                border: none;
            }}
            QProgressBar::chunk {{
                background: {T['accent2']};
            }}
            QComboBox {{
                background: {T['bg0']};
                color: {T['accent2']};
                border: 1px solid {T['border']};
                padding: 3px 6px;
            }}
            QComboBox::drop-down {{
                border: none;
                background: {T['bg2']};
            }}
            QComboBox QAbstractItemView {{
                background: {T['bg1']};
                color: {T['text']};
                border: 1px solid {T['border2']};
                selection-background-color: {T['bg2']};
            }}
        """)

    def _sb_item(self, layout, key, val):
        layout.addWidget(_make_label(key))
        v = QLabel(val)
        v.setObjectName("sb_val")
        from PySide6.QtGui import QFont as _QFont
        v.setFont(_QFont(T['font'].split(",")[0].strip().strip("'"), 9))
        v.setStyleSheet(f"color: {T['accent2']}; font-size: 9px;")
        layout.addWidget(v)
        return v

    def retranslateUi(self, MainWindow):
        pass

    # -- helpers called from MainWindow to update display -------------------
    def set_plugin_status(self, plugin, status, connected=False):
        """plugin: 'motion'|'probe'|'pattern'|'file'"""
        color = T['ok'] if connected else T['warn'] if status else T['dim']
        row = {
            "motion":  self._plug_motion,
            "probe":   self._plug_probe,
            "pattern": self._plug_pattern,
            "file":    self._plug_file,
        }.get(plugin)
        if row:
            row.set_status(status or "—", color)

    def set_mode(self, mode, color=None):
        self._mode_label.setText(mode.upper())
        c = color or T['muted']
        self._mode_label.setStyleSheet(f"""
            color: {c}; font-size: 10px; letter-spacing: 2px;
            border: 1px solid {T['border2']}; padding: 2px 8px;
        """)

    def set_dot(self, which, connected):
        dot = {"motion": self._dot_motion, "probe": self._dot_probe,
               "file": self._dot_file}.get(which)
        if dot:
            c = T['ok'] if connected else T['dim']
            dot.setStyleSheet(f"color: {c}; font-size: 7px; padding: 0 2px;")
