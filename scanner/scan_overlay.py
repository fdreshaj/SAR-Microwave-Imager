# scan_overlay.py
from PySide6.QtCore import Qt, QTimer, Signal, QThread
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QColor
from scanner.scope_loader import ScopeLoader


# ---------------------------------------------------------------------------
# Worker thread
# ---------------------------------------------------------------------------
class WorkerThread(QThread):
    """Runs a blocking callable off the main thread, emits done when finished."""
    done = Signal()

    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.setTerminationEnabled(True)

    def run(self):
        self.fn()
        self.done.emit()


# ---------------------------------------------------------------------------
# Overlay
# ---------------------------------------------------------------------------
class ScanOverlay(QWidget):
    """
    Frameless top-level window that covers MainWindow during blocking ops.

    Usage in MainWindow.__init__:
        self.scan_overlay = ScanOverlay(self)

    Usage when a blocking call is needed:
        def connect_motion(self):
            def _do():
                self.scanner.scanner.motion_controller.connect()
            self.scan_overlay.run_blocking(_do, callback=lambda: self.configure_motion(True))

    Theme support — call from MainWindow.toggle_theme():
        self.scan_overlay.set_theme('light')  # or 'dark'

    Minimize support — call from MainWindow.changeEvent():
        if self.isMinimized():
            self.scan_overlay.hide()
        elif self._worker_active():
            self.scan_overlay._refit()
            self.scan_overlay.show()
            self.scan_overlay.raise_()
    """

    def __init__(self, main_window, theme: str = "dark"):
        # Top-level frameless — avoids child-widget geometry/repaint issues
        super().__init__(None)
        self._main = main_window
        self._theme = theme

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("background: rgba(0, 0, 0, 160);")

        self.loader = ScopeLoader(self, ink=self._ink_color())
        self.loader.setFixedSize(200, 200)

        # Native widget needs an external nudge through translucent parent
        self._repaint_timer = QTimer(self)
        self._repaint_timer.setInterval(1000 // 60)
        self._repaint_timer.timeout.connect(self.loader.update)

        self._worker = None
        self.setVisible(False)

    # -- theming ------------------------------------------------------------
    def _ink_color(self) -> QColor:
        return QColor(10, 10, 10) if self._theme == "light" else QColor(255, 255, 255)

    def set_theme(self, theme: str):
        self._theme = theme
        self.loader.INK = self._ink_color()

    # -- geometry -----------------------------------------------------------
    def _refit(self):
        """Align overlay exactly over the main window (works across monitors)."""
        if self._main:
            self.setGeometry(self._main.frameGeometry())
        self._center_loader()

    def _center_loader(self):
        if self.width() > 0 and self.height() > 0:
            x = (self.width()  - self.loader.width())  // 2
            y = (self.height() - self.loader.height()) // 2
            self.loader.move(x, y)

    # -- visibility ---------------------------------------------------------
    def showEvent(self, e):
        self._repaint_timer.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self._repaint_timer.stop()
        super().hideEvent(e)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._center_loader()

    # -- blocking op --------------------------------------------------------
    def run_blocking(self, fn, callback=None):
        """
        Show the overlay, run fn() in a QThread, hide when done.
        callback fires on the main thread after fn() completes.
        """
        self._refit()
        self.show()
        self.raise_()

        self._worker = WorkerThread(fn)
        if callback:
            self._worker.done.connect(callback)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _on_done(self):
        self.hide()
        self._worker = None

    # -- cleanup ------------------------------------------------------------
    def cleanup(self):
        """Call from MainWindow.closeEvent."""
        self._repaint_timer.stop()
        if self._worker is not None and self._worker.isRunning():
            self._worker.quit()
            if not self._worker.wait(3000):
                self._worker.terminate()
                self._worker.wait()
        self._worker = None