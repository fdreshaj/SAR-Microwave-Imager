import math
from PySide6.QtCore import Qt, QTimer, QPointF
from PySide6.QtGui import QPainter, QPainterPath, QPen, QColor
from PySide6.QtWidgets import QWidget


class ScopeLoader(QWidget):
    PERIOD_MS = 2200
    FPS = 60
    STROKE = 2.4

    def __init__(self, parent=None, ink: QColor = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.INK = ink if ink is not None else QColor(10, 10, 10)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(int(1000 / self.FPS))

    def start(self):
        if not self._timer.isActive():
            self._timer.start(int(1000 / self.FPS))

    def stop(self):
        self._timer.stop()

    def hideEvent(self, e):
        self._timer.stop()
        super().hideEvent(e)

    def showEvent(self, e):
        self.start()
        super().showEvent(e)

    

    def _build_path(self, w, h):
        s = min(w, h) / 110.0
        ox = (w - 110 * s) / 2.0
        oy = (h - 110 * s) / 2.0
        mid, x0, x1, step = 55.0, 8.0, 102.0, 1.2

        path = QPainterPath()
        x = x0
        first = True
        while x <= x1 + 1e-6:
            y = mid - 36 * math.sin(2 * math.pi * (x - x0) / 30) \
                         * math.exp(-(x - x0) / 150)
            pt = QPointF(ox + x * s, oy + y * s)
            if first:
                path.moveTo(pt)
                first = False
            else:
                path.lineTo(pt)
            x += step
        return path

    @staticmethod
    def _slice(path, a, b):
        a, b = max(0.0, min(1.0, a)), max(0.0, min(1.0, b))
        if b <= a:
            return QPainterPath()
        out = QPainterPath()
        out.moveTo(path.pointAtPercent(a))
        n = max(2, int((b - a) * 220))
        for i in range(1, n + 1):
            t = a + (b - a) * i / n
            t = max(0.0, min(1.0, t))   # clamp every sample, not just a and b
            out.lineTo(path.pointAtPercent(t))
        return out

    def _tick(self):
        self._phase = (self._phase + 2.0 * (1000 / self.FPS) / self.PERIOD_MS) % 2.0
        self.update()

    def paintEvent(self, _):
        w, h = self.width(), self.height()
        path = self._build_path(w, h)

        DEAD_ZONE = 0.08  # fraction of phase to stay invisible between cycles

        if self._phase < 1.0:
            # Writing phase: head sweeps 0 -> 1
            head = min(1.0, max(0.0, self._ease(self._phase)))
            tail = 0.0
        elif self._phase < 2.0 - DEAD_ZONE:
            # Erasing phase: tail catches up, but stops just before head
            erase_t = (self._phase - 1.0) / (1.0 - DEAD_ZONE)
            head = 1.0
            tail = min(0.98, max(0.0, self._ease(erase_t)))  # never reaches 1.0
        else:
            # Dead zone — draw nothing, clean reset
            return

        seg = self._slice(path, tail, head)
        if seg.isEmpty():
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        scale = min(w, h) / 200.0
        pen = QPen(self.INK, self.STROKE * scale)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawPath(seg)

    @staticmethod
    def _ease(t):
        return 3 * t * t - 2 * t * t * t


if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    win = ScopeLoader()
    win.resize(200, 200)
    win.setWindowTitle("Scanning…")
    win.show()
    sys.exit(app.exec())