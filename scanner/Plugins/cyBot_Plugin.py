import math
import re
import time
import socket
import threading
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from datetime import datetime
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QVBoxLayout, QTextEdit, QSizePolicy, QPushButton,
    QLineEdit, QLabel, QFrame, QWidget
)
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QTextCursor

from scanner.plugin_setting import PluginSettingString, PluginSettingInteger
from scanner.motion_controller import MotionControllerPlugin

ROBOT_R = 10


class CyBotSignals(QObject):
    log_signal      = Signal(str, str)
    radar_signal    = Signal(float, float)
    objects_signal  = Signal(list)
    position_signal = Signal(float)
    moved_signal    = Signal(float)
    hazard_signal   = Signal(str)


class ObjectParser:
    OBJECT_LINE_RE = re.compile(
        r'Object\s+(\d+):\s*center=([0-9.]+)\s*deg,\s*PING=([0-9.]+)\s*cm,'
        r'\s*linear=([0-9.]+)\s*cm,\s*IR=(\d+)'
    )
    TABLE_ROW_RE = re.compile(
        r'^\s*(\d+)\s+([0-9.]+)\s+([0-9.]+)\s+(\d+)\s+([0-9.]+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$'
    )

    @staticmethod
    def parse(line: str) -> dict | None:
        m = ObjectParser.OBJECT_LINE_RE.search(line)
        if m:
            return {
                'index':        int(m.group(1)),
                'center':       float(m.group(2)),
                'distance':     float(m.group(3)),
                'linear_width': float(m.group(4)),
                'ir':           int(m.group(5)),
            }
        m = ObjectParser.TABLE_ROW_RE.match(line)
        if m:
            return {
                'index':        int(m.group(1)),
                'center':       float(m.group(2)),
                'distance':     float(m.group(3)),
                'linear_width': float(m.group(5)),
                'ir':           int(m.group(6)),
            }
        return None
class AspectRatioWidget(QWidget):
    """Wraps a widget and enforces a fixed aspect ratio, centering with letterboxing."""
    def __init__(self, widget, ratio_w: float, ratio_h: float, parent=None):
        super().__init__(parent)
        self._widget = widget
        self._ratio_w = ratio_w
        self._ratio_h = ratio_h
        self._widget.setParent(self)
        #self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w = self.width()
        h = self.height()
        if w == 0 or h == 0:
            return
        if w / h > self._ratio_w / self._ratio_h:
            # container is too wide — constrain by height
            new_h = h
            new_w = int(h * self._ratio_w / self._ratio_h)
        else:
            # container is too tall — constrain by width
            new_w = w
            new_h = int(w * self._ratio_h / self._ratio_w)
        x = (w - new_w) // 2
        y = (h - new_h) // 2
        self._widget.setGeometry(x, y, new_w, new_h)

class MinimapWidget(FigureCanvas):
    def __init__(self, parent=None):
        self.fig = Figure(figsize=(6, 6), facecolor='#0a0a0a')
        super().__init__(self.fig)
        self.setParent(parent)
        #self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # MinimapWidget and RadarWidget — replace the existing setSizePolicy line
        #self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self.ax = self.fig.add_subplot(111)
        self.fig.subplots_adjust(left=0.1, right=0.97, top=0.93, bottom=0.08)
        self._last_move_cm: float = 0.0
        self.x       = 0.0
        self.y       = 0.0
        self.heading = 90.0
        self.path    = [(0.0, 0.0)]

        self.world_objects: list[dict] = []
        self.hazard_objects: list[dict] = []

        self._view_half_x: float = 100.0
        self._view_half_y: float = 200.0

        self.target: tuple | None = None

        self._place_mode: bool = False
        self.mpl_connect('button_press_event', self._on_canvas_click)

        self._draw()

    def update_heading(self, angle_deg: float):
        self.heading = angle_deg
        self._draw()
    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width: int) -> int:
        return width
    def move_robot(self, dist_cm: float):
        rad     = math.radians(self.heading)
        self.x += dist_cm * math.cos(rad)
        self.y += dist_cm * math.sin(rad)
        self.path.append((self.x, self.y))
        self._draw()

    def add_objects(self, objects: list):
        for obj in objects:
            raw_dist   = obj.get('distance', 0.0)
            dist       = raw_dist if raw_dist > 1.0 else 30.0

            offset_deg = obj['center'] - 90.0
            global_rad = math.radians(self.heading + offset_deg)

            raw_lw = obj.get('linear_width', obj.get('l_width', 0.0))
            lw = raw_lw if raw_lw > 0.0 else math.pi * ROBOT_R
            radius = lw / math.pi
            center_dist = dist + radius

            gx = self.x + center_dist * math.cos(global_rad)
            gy = self.y + center_dist * math.sin(global_rad)

            self.world_objects.append({
                'gx':           gx,
                'gy':           gy,
                'radius':       radius,
                'linear_width': lw,
                'raw_lw':       raw_lw,
                'distance':     dist,
                'center':       obj['center'],
                'index':        obj.get('index', len(self.world_objects) + 1),
                'ir':           obj.get('ir', 0),
                'ping_zero':    raw_dist <= 1.0,
                'width_zero':   raw_lw <= 0.0,
            })
        self._draw()

    def clear_objects(self):
        self.world_objects = []
        self.hazard_objects = []
        self._view_half_x = 100.0
        self._view_half_y = 200.0
        self._draw()

    def set_target(self, x: float, y: float):
        self.target = (x, y)
        self._draw()

    def clear_target(self):
        self.target = None
        self._draw()

    def add_hazard(self, kind: str):
        dist = ROBOT_R * 2.0
        fwd_rad = math.radians(self.heading)
        gx = self.x + dist * math.cos(fwd_rad)
        gy = self.y + dist * math.sin(fwd_rad)
        self.hazard_objects.append({'gx': gx, 'gy': gy, 'kind': kind})
        self._draw()

    def set_place_mode(self, active: bool):
        self._place_mode = active
        from PySide6.QtCore import Qt
        self.setCursor(Qt.CrossCursor if active else Qt.ArrowCursor)

    def _on_canvas_click(self, event):
        if not self._place_mode or event.inaxes is None:
            return
        self.x = event.xdata
        self.y = event.ydata
        self.path.append((self.x, self.y))
        self._draw()

    def _draw(self):
        ax = self.ax
        ax.clear()

        ax.set_facecolor('#0a0a0a')
        ax.tick_params(colors='#336633', labelsize=7)
        for spine in ax.spines.values():
            spine.set_color('#1a3a1a')
        ax.grid(True, color='#1a3a1a', linewidth=0.5, linestyle='--')
        ax.set_title('Robot Minimap', color='#00ff41', fontsize=10, pad=6)
        ax.set_xlabel('X (cm)', color='#336633', fontsize=8)
        ax.set_ylabel('Y (cm)', color='#336633', fontsize=8)

        ax.axhline(0, color='#1a3a1a', linewidth=0.8, linestyle=':')
        ax.axvline(0, color='#1a3a1a', linewidth=0.8, linestyle=':')
        ax.plot(0, 0, marker='+', color='#336633',
                markersize=10, markeredgewidth=1, zorder=2)

        if len(self.path) > 1:
            px, py = zip(*self.path)
            ax.plot(px, py, color='#336633', linewidth=1.2,
                    linestyle='--', zorder=3)
            ax.scatter(list(px[:-1]), list(py[:-1]),
                       c='#336633', s=18, zorder=4,
                       edgecolors='none', alpha=0.7)

        ax.plot(self.path[0][0], self.path[0][1],
                marker='o', color='#00aaff', markersize=8,
                markeredgecolor='white', markeredgewidth=0.8,
                zorder=5, label='Start')

        for obj in self.world_objects:
            gx, gy = obj['gx'], obj['gy']

            ax.plot([self.x, gx], [self.y, gy],
                    color='#660000', linewidth=0.8,
                    linestyle=':', zorder=6)

            circle_r = obj['radius']
            obj_circle = plt.Circle(
                (gx, gy), circle_r,
                facecolor='#550000', edgecolor='#ff2222',
                linewidth=2.0, alpha=0.85, zorder=7
            )
            ax.add_patch(obj_circle)

            dist_label  = f"~30cm*" if obj['ping_zero']  else f"{obj['distance']:.0f}cm"
            width_label = f"~{obj['linear_width']:.1f}cm*" if obj['width_zero'] else f"{obj['linear_width']:.1f}cm"
            ax.text(
                gx, gy + circle_r + 2,
                f"O{obj['index']}  {dist_label}\nW={width_label}",
                color='#ff6666', fontsize=6,
                ha='center', va='bottom', zorder=9,
                bbox=dict(boxstyle='round,pad=0.2', facecolor='#1a0000',
                          edgecolor='#660000', alpha=0.85)
            )

        for hz in self.hazard_objects:
            hx, hy = hz['gx'], hz['gy']
            if hz['kind'] == 'bump':
                color, label = '#aa00ff', 'BUMP'
            else:
                color, label = '#222222', 'CLIFF'
            hz_circle = plt.Circle(
                (hx, hy), ROBOT_R,
                facecolor=color, edgecolor='white',
                linewidth=1.2, alpha=0.85, zorder=7
            )
            ax.add_patch(hz_circle)
            ax.text(
                hx, hy, label,
                color='white', fontsize=5, fontweight='bold',
                ha='center', va='center', zorder=8
            )

        if self.target is not None:
            tx, ty = self.target
            target_circle = plt.Circle(
                (tx, ty), ROBOT_R * 0.6,
                facecolor='none', edgecolor='#0088ff',
                linewidth=2.0, linestyle='--', zorder=8
            )
            ax.add_patch(target_circle)
            ax.plot([tx - ROBOT_R, tx + ROBOT_R], [ty, ty],
                    color='#0088ff', linewidth=1.2, zorder=8)
            ax.plot([tx, tx], [ty - ROBOT_R, ty + ROBOT_R],
                    color='#0088ff', linewidth=1.2, zorder=8)
            ax.text(
                tx, ty + ROBOT_R * 0.6 + 2,
                f"T({tx:.1f}, {ty:.1f})",
                color='#0088ff', fontsize=6,
                ha='center', va='bottom', zorder=9,
                bbox=dict(boxstyle='round,pad=0.2', facecolor='#00001a',
                          edgecolor='#003388', alpha=0.85)
            )
            self._view_half_x = max(self._view_half_x, abs(tx - self.x) + ROBOT_R * 2)
            self._view_half_y = max(self._view_half_y, abs(ty - self.y) + ROBOT_R * 2)

        robot_circle = plt.Circle(
            (self.x, self.y), ROBOT_R,
            facecolor='#0d2b0d', edgecolor='#00ff41',
            linewidth=2.0, zorder=10
        )
        ax.add_patch(robot_circle)

        rad = math.radians(self.heading)
        tx  = self.x + ROBOT_R * 0.82 * math.cos(rad)
        ty  = self.y + ROBOT_R * 0.82 * math.sin(rad)
        ax.annotate(
            '', xy=(tx, ty), xytext=(self.x, self.y),
            arrowprops=dict(facecolor='#00ff41', edgecolor='#00ff41',
                            width=2.5, headwidth=9, headlength=7),
            zorder=11
        )

        ax.text(
            self.x + ROBOT_R + 2, self.y + ROBOT_R + 2,
            f"({self.x:.1f}, {self.y:.1f})\n{self.heading:.0f}°",
            color='#00ff41', fontsize=7, zorder=12,
            bbox=dict(boxstyle='round,pad=0.2', facecolor='#050505',
                      edgecolor='#1a3a1a', alpha=0.8)
        )

        legend_handles = [
            mpatches.Patch(color='#00aaff', label='Start'),
            mpatches.Patch(color='#336633', label='Path'),
            mpatches.Patch(color='#00ff41', label='Robot'),
        ]
        if self.world_objects:
            legend_handles.append(
                mpatches.Patch(color='red',
                               label=f'Objects ({len(self.world_objects)})  * = PING fallback')
            )
        bump_count  = sum(1 for h in self.hazard_objects if h['kind'] == 'bump')
        cliff_count = sum(1 for h in self.hazard_objects if h['kind'] == 'cliff')
        if bump_count:
            legend_handles.append(mpatches.Patch(color='#aa00ff', label=f'Bump ({bump_count})'))
        if cliff_count:
            legend_handles.append(mpatches.Patch(color='#222222', label=f'Cliff ({cliff_count})'))
        if self.target is not None:
            legend_handles.append(
                mpatches.Patch(color='#0088ff', label=f'Target ({self.target[0]:.1f}, {self.target[1]:.1f})')
            )
        ax.legend(handles=legend_handles, loc='upper right', fontsize=6,
                  facecolor='#0a0a0a', edgecolor='#1a3a1a', labelcolor='#00ff41')

        pad = ROBOT_R * 2.0
        for obj in self.world_objects:
            r = obj['radius']
            self._view_half_x = max(self._view_half_x, abs(obj['gx'] - self.x) + r + pad)
            self._view_half_y = max(self._view_half_y, abs(obj['gy'] - self.y) + r + pad)

        ax.set_xlim(self.x - self._view_half_x, self.x + self._view_half_x)
        ax.set_ylim(self.y - self._view_half_y, self.y + self._view_half_y)

        self.draw()


class RadarWidget(FigureCanvas):
    def __init__(self, parent=None):
        self.fig = Figure(figsize=(4, 3), facecolor='#0a0a0a')
        super().__init__(self.fig)
        self.setParent(parent)
        # MinimapWidget and RadarWidget — replace the existing setSizePolicy line
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self.ax = self.fig.add_subplot(111, polar=True)
        self.fig.subplots_adjust(left=0.05, right=0.95, top=0.90, bottom=0.05)
        self._setup_axes()

        self.raw_points     = []
        self.object_lines   = []
        self._current_angle = 0.0

    def _setup_axes(self):
        ax = self.ax
        ax.set_facecolor('#0a0a0a')
        ax.set_thetamin(0)
        ax.set_thetamax(180)
        ax.set_theta_zero_location('W')
        ax.set_theta_direction(1)
        ax.set_ylim(0, 100)
        ax.set_rlabel_position(45)
        ax.tick_params(colors='#00ff41', labelsize=6)
        ax.spines['polar'].set_color('#1a3a1a')
        for gl in ax.xaxis.get_gridlines() + ax.yaxis.get_gridlines():
            gl.set_color('#1a3a1a')
            gl.set_linewidth(0.4)
        ax.set_thetagrids(
            [0, 45, 90, 135, 180],
            labels=['0°', '45°', 'FWD', '135°', '180°'],
            color='#00ff41', fontsize=6
        )
        ax.set_rgrids(
            [25, 50, 75, 100],
            labels=['25', '50', '75', '100'],
            color='#336633', fontsize=5
        )
    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width: int) -> int:
        return int(width * 3 / 4)

    def add_point(self, angle_deg: float, dist_cm: float):
        self._current_angle = angle_deg
        self.raw_points.append((np.radians(angle_deg), min(dist_cm, 99)))
        self._redraw()

    def set_objects(self, objects: list):
        self.object_lines = objects
        self._redraw()

    def clear_scan(self):
        self.raw_points   = []
        self.object_lines = []
        self._redraw()

    def _redraw(self):
        self.ax.clear()
        self._setup_axes()

        theta = np.radians(self._current_angle)

        self.ax.bar(theta, 100, width=np.radians(16),
                    bottom=0, alpha=0.08, color='cyan', zorder=1)

        if self.raw_points:
            ra, rd = zip(*self.raw_points)
            self.ax.scatter(ra, rd, c='#00ff41', s=6,
                            alpha=0.35, edgecolors='none', zorder=2)

        for obj in self.object_lines:
            obj_rad  = np.radians(obj['center'])
            raw_dist = obj.get('distance', 0.0)
            obj_dist = min(raw_dist if raw_dist > 1.0 else 30.0, 98)
            lw_val   = obj.get('linear_width', obj.get('l_width', 0.0))

            self.ax.plot([obj_rad, obj_rad], [0, obj_dist],
                         color='red', linewidth=1.5, zorder=3)
            self.ax.scatter([obj_rad], [obj_dist],
                            c='red', s=60, marker='D',
                            edgecolors='white', linewidths=0.5, zorder=4)
            self.ax.annotate(
                f"W={lw_val:.1f}",
                xy=(obj_rad, obj_dist),
                xytext=(obj_rad + np.radians(8), min(obj_dist + 10, 93)),
                color='#ff6666', fontsize=5,
                arrowprops=dict(arrowstyle='->', color='#ff6666', lw=0.6)
            )

        self.ax.annotate(
            '', xy=(theta, 83), xytext=(theta, 5),
            arrowprops=dict(facecolor='#00ff41', edgecolor='#00ff41',
                            width=1.2, headwidth=7, headlength=5)
        )

        self.draw()


class UARTConsole(QTextEdit):
    COLORS = {
        'info': '#00ff41',
        'warn': '#ffaa00',
        'data': '#00aaff',
        'cmd':  '#ff6666',
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setStyleSheet("""
            QTextEdit {
                background-color: #050505;
                color: #00ff41;
                font-family: 'Courier New', monospace;
                font-size: 9px;
                border: 1px solid #1a3a1a;
            }
        """)
        self.document().setMaximumBlockCount(500)

    def append_message(self, message: str, level: str = 'info'):
        color = self.COLORS.get(level, '#00ff41')
        ts    = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        html  = (f'<span style="color:#336633">[{ts}]</span> '
                 f'<span style="color:{color}">{message}</span>')
        self.append(html)
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.setTextCursor(cursor)


class CommandCenterDialog(QDialog):
    def __init__(self, signals: CyBotSignals, plugin=None, parent=None):
        super().__init__(parent)
        self._plugin = plugin
        self.setWindowTitle("CyBot Command Center")
        self.resize(1100, 620)
        self.setStyleSheet("background-color: #050505;")

        signals.log_signal.connect(self._on_log)
        signals.radar_signal.connect(self._on_radar)
        signals.objects_signal.connect(self._on_objects)
        signals.hazard_signal.connect(self._on_hazard)
        signals.position_signal.connect(self._on_heading)
        signals.moved_signal.connect(self._on_moved)

        root = QHBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        left_col = QVBoxLayout()
        left_col.setSpacing(4)

        
        self.minimap = MinimapWidget(self)
        self._minimap_wrap = AspectRatioWidget(self.minimap, 1, 1, self)
        left_col.addWidget(self._minimap_wrap, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)

        self.clear_btn = QPushButton("Clear Objects")
        self.clear_btn.setFixedHeight(28)
        self.clear_btn.setStyleSheet("""
            QPushButton {
                background-color: #1a0000;
                color: #ff4444;
                border: 1px solid #660000;
                border-radius: 3px;
                font-family: 'Courier New', monospace;
                font-size: 10px;
                font-weight: bold;
            }
            QPushButton:hover   { background-color: #330000; border-color: #ff2222; }
            QPushButton:pressed { background-color: #550000; }
        """)
        self.clear_btn.clicked.connect(self._on_clear_objects)
        btn_row.addWidget(self.clear_btn)

        self.place_btn = QPushButton("Move Bot")
        self.place_btn.setFixedHeight(28)
        self.place_btn.setCheckable(True)
        self._place_btn_style_off = """
            QPushButton {
                background-color: #0a0a0a;
                color: #ffaa00;
                border: 1px solid #664400;
                border-radius: 3px;
                font-family: 'Courier New', monospace;
                font-size: 10px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #1a1000; border-color: #ffaa00; }
        """
        self._place_btn_style_on = """
            QPushButton {
                background-color: #332200;
                color: #ffdd00;
                border: 2px solid #ffaa00;
                border-radius: 3px;
                font-family: 'Courier New', monospace;
                font-size: 10px;
                font-weight: bold;
            }
        """
        self.place_btn.setStyleSheet(self._place_btn_style_off)
        self.place_btn.toggled.connect(self._on_place_mode_toggled)
        btn_row.addWidget(self.place_btn)

        left_col.addLayout(btn_row)
        root.addLayout(left_col, stretch=2)

        right_col = QVBoxLayout()
        right_col.setSpacing(4)

        # self.radar = RadarWidget(self)
        # self.radar.setMinimumHeight(280)
        # right_col.addWidget(self.radar, stretch=1)
        self.radar = RadarWidget(self)
        self._radar_wrap = AspectRatioWidget(self.radar, 4, 3, self)
        right_col.addWidget(self._radar_wrap, stretch=1)

        target_frame = QFrame(self)
        target_frame.setStyleSheet("""
            QFrame {
                background-color: #050510;
                border: 1px solid #003388;
                border-radius: 3px;
            }
        """)
        target_layout = QVBoxLayout(target_frame)
        target_layout.setContentsMargins(6, 4, 6, 4)
        target_layout.setSpacing(3)

        target_title = QLabel("Target Coordinates (cm)")
        target_title.setStyleSheet("color: #0088ff; font-family: 'Courier New', monospace; font-size: 9px; font-weight: bold;")
        target_layout.addWidget(target_title)

        coord_row = QHBoxLayout()
        coord_row.setSpacing(4)

        lbl_x = QLabel("X:")
        lbl_x.setStyleSheet("color: #336699; font-family: 'Courier New', monospace; font-size: 9px;")
        lbl_x.setFixedWidth(14)
        self.target_x_input = QLineEdit("0")
        self.target_x_input.setFixedHeight(22)
        self.target_x_input.setStyleSheet("""
            QLineEdit {
                background-color: #00001a;
                color: #0088ff;
                border: 1px solid #003388;
                border-radius: 2px;
                font-family: 'Courier New', monospace;
                font-size: 9px;
                padding: 1px 3px;
            }
            QLineEdit:focus { border-color: #0055cc; }
        """)

        lbl_y = QLabel("Y:")
        lbl_y.setStyleSheet("color: #336699; font-family: 'Courier New', monospace; font-size: 9px;")
        lbl_y.setFixedWidth(14)
        self.target_y_input = QLineEdit("0")
        self.target_y_input.setFixedHeight(22)
        self.target_y_input.setStyleSheet(self.target_x_input.styleSheet())

        self.set_target_btn = QPushButton("Set Target")
        self.set_target_btn.setFixedHeight(22)
        self.set_target_btn.setStyleSheet("""
            QPushButton {
                background-color: #00001a;
                color: #0088ff;
                border: 1px solid #003388;
                border-radius: 2px;
                font-family: 'Courier New', monospace;
                font-size: 9px;
                font-weight: bold;
            }
            QPushButton:hover   { background-color: #000033; border-color: #0055cc; }
            QPushButton:pressed { background-color: #000055; }
        """)
        self.set_target_btn.clicked.connect(self._on_set_target)

        self.clear_target_btn = QPushButton("Clear")
        self.clear_target_btn.setFixedHeight(22)
        self.clear_target_btn.setFixedWidth(44)
        self.clear_target_btn.setStyleSheet("""
            QPushButton {
                background-color: #0a0a0a;
                color: #336699;
                border: 1px solid #1a3a1a;
                border-radius: 2px;
                font-family: 'Courier New', monospace;
                font-size: 9px;
            }
            QPushButton:hover   { background-color: #111111; border-color: #0088ff; color: #0088ff; }
        """)
        self.clear_target_btn.clicked.connect(self._on_clear_target)

        coord_row.addWidget(lbl_x)
        coord_row.addWidget(self.target_x_input)
        coord_row.addWidget(lbl_y)
        coord_row.addWidget(self.target_y_input)
        coord_row.addWidget(self.set_target_btn)
        coord_row.addWidget(self.clear_target_btn)
        target_layout.addLayout(coord_row)

        right_col.addWidget(target_frame)

        self.console = UARTConsole(self)
        self.console.setMinimumHeight(160)
        right_col.addWidget(self.console, stretch=1)

        root.addLayout(right_col, stretch=1)

    def _on_log(self, message: str, level: str):
        self.console.append_message(message, level)

    def _on_radar(self, angle: float, dist: float):
        self.radar.add_point(angle, dist)

    def _on_objects(self, objects: list):
        self.radar.set_objects(objects)
        self.minimap.add_objects(objects)

    def _on_heading(self, angle: float):
        self.minimap.update_heading(angle)

    def _on_moved(self, dist: float):
        self.minimap.move_robot(dist)

    def _on_set_target(self):
        try:
            x = float(self.target_x_input.text())
            y = float(self.target_y_input.text())
            self.minimap.set_target(x, y)
        except ValueError:
            pass

    def _on_clear_target(self):
        self.minimap.clear_target()

    def _on_place_mode_toggled(self, checked: bool):
        self.minimap.set_place_mode(checked)
        if checked:
            self.place_btn.setStyleSheet(self._place_btn_style_on)
            self.place_btn.setText("Move Bot: ON")
            self.console.append_message("Place mode ON — click minimap to teleport robot", 'warn')
        else:
            self.place_btn.setStyleSheet(self._place_btn_style_off)
            self.place_btn.setText("Move Bot")
            self.console.append_message("Place mode OFF", 'info')

    def _on_hazard(self, kind: str):
        self.minimap.add_hazard(kind)
        label = 'BUMP FOUND' if kind == 'bump' else 'CLIFF FOUND'
        self.console.append_message(f"{label} — marked on minimap", 'warn')

    def _on_clear_objects(self):
        self.minimap.clear_objects()
        self.radar.clear_scan()
        if self._plugin:
            self._plugin.clear_pending_objects()
        self.console.append_message("Objects cleared", 'warn')


class motion_controller_plugin(MotionControllerPlugin):
    def __init__(self):
        super().__init__()

        self.address = PluginSettingString("IP Address", "192.168.1.1")
        self.port    = PluginSettingInteger("Port", 288)
        self.timeout = PluginSettingInteger("Timeout (ms)", 10000)
        self.add_setting_pre_connect(self.address)
        self.add_setting_pre_connect(self.port)
        self.add_setting_pre_connect(self.timeout)

        self.cybot            = None
        self.read_thread      = None
        self.read_thread_cond = False
        self.log_filename     = "cybot_data_log.txt"
        self.ok_received      = threading.Event()

        self.turn_finished = threading.Event()
        self.move_finished = threading.Event()

        self._command_history: list[tuple[str, int]] = []

        self.signals        = CyBotSignals()
        self.command_center = CommandCenterDialog(self.signals, plugin=self)

        self._scan_angles: list[float] = []
        self._scan_dists:  list[float] = []

        self._pending_objects: list[dict] = []
        self._in_object_block = False

    def clear_pending_objects(self):
        self._pending_objects = []
        self._in_object_block = False

    def connect(self):
        try:
            self.cybot = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.cybot.settimeout(self.timeout.value / 1000)
            self.cybot.connect((self.address.value, self.port.value))
            self.signals.log_signal.emit(
                f"Connected to {self.address.value}:{self.port.value}", 'info'
            )
            self.read_thread_cond = True
            self.read_thread = threading.Thread(
                target=self.read_thread_interrupt, daemon=True
            )
            self.read_thread.start()
            self.command_center.show()
        except Exception as e:
            print(f"Failed to connect: {e}")
            self.cybot = None

    def read_thread_interrupt(self):
        self.signals.log_signal.emit(f"Logging to {self.log_filename}", 'info')
        recv_buf = ""
        with open(self.log_filename, "a") as f:
            f.write(f"\n--- Session Started: {datetime.now()} ---\n")
            while self.read_thread_cond:
                try:
                    data = self.cybot.recv(1024)
                    if not data:
                        break

                    recv_buf += data.decode('utf-8', errors='ignore')

                    while '\n' in recv_buf:
                        line, recv_buf = recv_buf.split('\n', 1)
                        decoded = line.strip()
                        if not decoded:
                            continue

                        self.signals.log_signal.emit(f"RX: {decoded}", 'data')
                        self._parse_line(decoded)

                        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                        f.write(f"[{ts}] RX: {decoded}\n")
                        f.flush()

                except socket.timeout:
                    continue
                except Exception:
                    break

    def _parse_line(self, decoded: str):
        if "OK" in decoded:
            self.ok_received.set()
            self.signals.log_signal.emit("Robot: path clear", 'info')
        elif "CORRECTION" in decoded:
            self.signals.log_signal.emit("Robot: course correction", 'warn')

        if "center=" in decoded and "PING=" in decoded and "Object" not in decoded:
            try:
                angle_val = float(decoded.split("center=")[1].split(" deg")[0])
                dist_val  = float(decoded.split("PING=")[1].split(" cm")[0])
                self._scan_angles.append(angle_val)
                self._scan_dists.append(dist_val)
                self.signals.radar_signal.emit(angle_val, dist_val)
                if angle_val >= 178:
                    self._scan_angles = []
                    self._scan_dists  = []
            except:
                pass

        parsed = ObjectParser.parse(decoded)
        if parsed:
            self._pending_objects.append({
                'index':        parsed['index'],
                'center':       parsed['center'],
                'distance':     parsed['distance'],
                'linear_width': parsed['linear_width'],
                'l_width':      parsed['linear_width'],
                'ir':           parsed['ir'],
            })
            self.signals.log_signal.emit(
                f"Object {parsed['index']} | "
                f"{parsed['center']:.0f}° "
                f"PING={parsed['distance']:.1f}cm "
                f"W={parsed['linear_width']:.1f}cm "
                f"IR={parsed['ir']}",
                'warn'
            )

        if "Detected Objects" in decoded:
            self._in_object_block = True

        if self._in_object_block and "===" in decoded and self._pending_objects:
            self.signals.objects_signal.emit(list(self._pending_objects))
            self._pending_objects  = []
            self._in_object_block  = False

        if "Angle" in decoded and "center=" not in decoded:
            try:
                angle = float(decoded.split("Angle")[1].strip().split()[0])
                self.signals.position_signal.emit(angle)
            except:
                pass

        # ---- UPDATED: hazard events with early-stop position correction ----
        # The bot sends "BUMP FOUND at 45" or "CLIFF FOUND at 45" when it stops
        # mid-move. The distance is how far it actually travelled. We emit
        # moved_signal first to correct self.x/y, then hazard_signal places
        # the marker one robot-length ahead of the corrected position.
        upper = decoded.upper()
        for hazard_kind, keyword in (('bump', 'BUMP FOUND'), ('cliff', 'CLIFF FOUND')):
            if keyword in upper:
                try:
                    dist_traveled_mm = float(decoded.split('at')[1].strip().split()[0])
                    # Step 1: rewind to the position before the move was issued
                    self.signals.moved_signal.emit(-self._last_move_cm)
                    # Step 2: advance by the distance the bot actually covered
                    self.signals.moved_signal.emit(dist_traveled_mm / 10.0)
                    self.signals.log_signal.emit(
                        f"Hazard early-stop: rewound {self._last_move_cm:.1f}cm, "
                        f"re-applied {dist_traveled_mm:.1f}mm", 'warn'
                    )
                except (IndexError, ValueError):
                    pass  # No distance in message — position already correct
                self.signals.hazard_signal.emit(hazard_kind)
        # ---- end update ----

        if "Turn Finished" in decoded:
            self.turn_finished.set()
        if "Movement Finished" in decoded:
            self.move_finished.set()

        if "Moved" in decoded:
            try:
                dist = float(decoded.split("Moved")[1].strip().split()[0])
                self.signals.moved_signal.emit(dist)
                self.signals.log_signal.emit(f"Position +{dist}cm", 'cmd')
            except:
                pass

        if "Data:" in decoded:
            try:
                parts  = decoded.split(",")
                u_dist = float(parts[0].split("Ultrasound")[1].strip())
                ir_val = float(parts[1].split("IR")[1].strip())
                angle  = float(parts[2].split("Angle")[1].strip())
                self.signals.position_signal.emit(angle)
                self.signals.log_signal.emit(
                    f"US:{u_dist:.1f}cm IR:{ir_val:.0f} Ang:{angle:.0f}°", 'data'
                )
            except Exception as pe:
                self.signals.log_signal.emit(f"Parse err: {pe}", 'warn')

    def disconnect(self):
        self.read_thread_cond = False
        if self.read_thread:
            self.read_thread.join(timeout=2.0)
        if self.cybot:
            try:
                self.cybot.close()
            except:
                pass
            self.signals.log_signal.emit("Disconnected", 'warn')

    def send_gcode_command(self, command):
        if isinstance(command, int):
            command = str(command)
        if self.cybot:
            self.cybot.send((command + "\n").encode('utf-8'))
            self.signals.log_signal.emit(f"TX: {command}", 'cmd')

    def get_channel_names(self):              return super().get_channel_names()
    def get_xaxis_coords(self):               return super().get_xaxis_coords()
    def get_xaxis_units(self):                return super().get_xaxis_units()
    def get_yaxis_units(self):                return super().get_yaxis_units()
    def get_axis_display_names(self) -> tuple[str, ...]: pass
    def get_axis_units(self) -> tuple[str, ...]:         pass
    def set_velocity(self, velocities: dict[int, float] = None) -> None: pass
    def set_acceleration(self, accels: dict[int, float] = None) -> None: pass
    def scan_begin(self):                     return super().scan_begin()
    def scan_end(self):                       return super().scan_end()
    def scan_read_measurement(self, i, l):    return super().scan_read_measurement(i, l)
    def scan_trigger_and_wait(self, i, l):    return super().scan_trigger_and_wait(i, l)
    def move_relative(self, p) -> dict[int, float] | None: pass
    def get_current_positions(self) -> tuple[float, ...]: pass
    def is_moving(self, axis=None) -> bool:   pass
    def get_endstop_minimums(self) -> tuple[float, ...]: pass
    def get_endstop_maximums(self) -> tuple[float, ...]: pass
    def set_config(self, amps, idle_p, idle_time): pass
    def emergency_stop(self): pass

    def move_absolute(self, move_dist: dict[int, float]) -> dict[int, float] | None:
        for key, val in move_dist.items():
            raw_str     = str(int(abs(val)))
            is_negative = val < 0
            if key == 0:
                prefix = "rr" if is_negative else "rl"
            elif key == 1:
                prefix = "mb" if is_negative else "mf"
            else:
                prefix = "imu"
            if   prefix == 'mf':  cmd = '000' + raw_str
            elif prefix == 'mb':  cmd = '010' + raw_str
            elif prefix == 'rl':  cmd = '100' + raw_str
            elif prefix == 'rr':  cmd = '110' + raw_str
            else:                  cmd = '101' + raw_str
            self.send_gcode_command(cmd)
            if prefix in ('mf', 'mb'):
                dist_cm = (abs(val) / 10.0) * (-1 if is_negative else 1)
                self.signals.moved_signal.emit(float(dist_cm))
                self._last_move_cm = float(dist_cm)
                self._command_history.append((prefix, int(abs(val) / 10.0) * (1 if not is_negative else -1)))
            elif prefix in ('rl', 'rr'):
                current = self.command_center.minimap.heading
                delta   = abs(val) * (1 if prefix == 'rr' else -1)
                self.signals.position_signal.emit((current + delta) % 360)
                self._command_history.append((prefix, int(abs(val)) * (1 if not is_negative else -1)))

    def home(self, axes=None):
        self.nav()

    def nav(self):
        self.send_gcode_command("001000")

    def execute_trajectory(self, radius: float, angle_deg: float):
        self.send_gcode_command(f"100{int(angle_deg):03d}")
        self.signals.position_signal.emit(float(angle_deg))
        time.sleep(1)
        step_size = 100.0
        for _ in range(0, int(radius), int(step_size)):
            time.sleep(1)
            self.send_gcode_command(f"000{int(step_size):03d}")
            self.signals.moved_signal.emit(step_size)
            time.sleep(1)
        self.signals.log_signal.emit("Trajectory finished", 'info')

    def create_grid(self, anchorsx, anchorsy, targetx, targety, hqx, hqy):
        if len(anchorsx) < 3 or len(anchorsy) < 3:
            raise ValueError("Three anchors required.")
        ox, oy     = anchorsx[0], anchorsy[0]
        v1_x, v1_y = anchorsx[1]-ox, anchorsy[1]-oy
        v2_x, v2_y = anchorsx[2]-ox, anchorsy[2]-oy
        d1 = math.sqrt(v1_x**2 + v1_y**2)
        d2 = math.sqrt(v2_x**2 + v2_y**2)
        s1x, s1y = v1_x/d1, v1_y/d1
        s2x, s2y = v2_x/d2, v2_y/d2
        grid, flat = [], []
        for i in range(int(d1)+1):
            row = []
            for j in range(int(d2)+1):
                p = (round(ox + i*s1x + j*s2x, 3),
                     round(oy + i*s1y + j*s2y, 3))
                row.append(p); flat.append(p)
            grid.append(row)
        dx, dy    = targetx-hqx, targety-hqy
        radius    = math.sqrt(dx**2+dy**2)
        angle_deg = math.degrees(math.atan2(dy, dx))
        return grid, (radius, angle_deg), flat

    def visualize(self, anchorsx, anchorsy, target, hq, grid_points_flat):
        plt.figure(figsize=(10, 10))
        gx, gy = zip(*grid_points_flat) if grid_points_flat else ([], [])
        plt.scatter(gx, gy, color='lightgrey', s=1, label='1mm Grid')
        plt.plot(anchorsx, anchorsy, 'kX-', markersize=10, label='Anchors (A0 corner)')
        for i in range(len(anchorsx)):
            plt.text(anchorsx[i], anchorsy[i], f'A{i}', fontsize=12, fontweight='bold')
        plt.plot(hq[0], hq[1], 'bo', markersize=10, label='HQ')
        plt.plot(target[0], target[1], 'r*', markersize=15, label='Target')
        plt.annotate('', xy=(target[0], target[1]), xytext=(hq[0], hq[1]),
                     arrowprops=dict(facecolor='blue', shrink=0.05, width=2, headwidth=8))
        plt.title('Grid and HQ-to-Target Trajectory', fontsize=16)
        plt.xlabel('X (mm)', fontsize=12)
        plt.ylabel('Y (mm)', fontsize=12)
        plt.axis('equal')
        plt.grid(True, which='both', linestyle='--', linewidth=0.5)
        plt.legend(loc='upper right')
        plt.show()

    def analyze_data(self, angles, avg_distance_cm):
        objects, thresh, obj_idx = [], 50.0, []
        for i in range(len(avg_distance_cm)):
            if avg_distance_cm[i] < thresh:
                obj_idx.append(i)
            else:
                if obj_idx:
                    objects.append(self._create_object_dict(obj_idx, angles, avg_distance_cm))
                    obj_idx = []
        if obj_idx:
            objects.append(self._create_object_dict(obj_idx, angles, avg_distance_cm))
        return objects

    def _create_object_dict(self, indices, angles, dists):
        sa    = angles[indices[0]]
        ea    = angles[indices[-1]]
        ctr   = (sa + ea) / 2
        wdeg  = ea - sa or 2
        adist = sum(dists[i] for i in indices) / len(indices)
        lw    = (adist * math.pi * wdeg) / 180
        obj   = {
            "center":       ctr,
            "l_width":      lw,
            "linear_width": lw,
            "distance":     min(dists[i] for i in indices),
            "index":        len(self._scan_angles),
            "ir":           0,
        }
        self.signals.log_signal.emit(
            f"Object | {ctr:.0f}° {obj['distance']:.1f}cm W:{lw:.1f}cm", 'warn'
        )
        return obj

    def smallest_obj(self, objects):
        if not objects:
            self.signals.log_signal.emit("No objects found.", 'warn')
            return
        smob    = min(objects, key=lambda x: x.get('linear_width', x.get('l_width', 0)))
        tarang  = int(smob['center'])
        tardist = int(max(0, smob['distance'] - 6))
        self.signals.log_signal.emit(f"Navigating: {tarang}° {tardist}cm", 'cmd')
        self.send_gcode_command(f"10{tarang:03d}")
        time.sleep(1.5)
        self.send_gcode_command(f"00{tardist:03d}")

    def ir_to_cm(self, raw_adc):
        if raw_adc <= 0: return 80.0
        v = raw_adc * (3.3 / 4095.0)
        if v < 0.4: return 80.0
        return max(0.0, min((1 / v) - 0.42, 80.0))

    def get_latest_ir_from_log(self):
        try:
            with open(self.log_filename, "r") as f:
                for line in reversed(f.readlines()):
                    if "IR" in line:
                        return float(line.split("IR")[1].split(",")[0].strip())
        except:
            return None

    @staticmethod
    def apply_adc_averaging(fp, window_size=5):
        raw = []
        try:
            with open(fp, 'r') as f:
                for line in f:
                    if "Data:" in line:
                        parts = line.split("Data:")[1]
                        if len(parts) > 1:
                            try:
                                raw.append(float(parts[1].strip().split()[0]))
                            except Exception as e:
                                print(f"Read error: {e}")
            if len(raw) < window_size:
                return None
            smoothed = []
            for i in range(len(raw)):
                w = raw[max(0, i - window_size + 1):i + 1]
                smoothed.append(round(sum(w) / len(w), 4))
            return smoothed
        except Exception as e:
            print(f"File error: {e}")
            return None

    def show_radar(self):
        self.command_center.show()