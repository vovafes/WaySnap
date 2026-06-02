from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent, QPaintEvent, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget


class _CanvasWidget(QWidget):
    """Inner widget that owns the background screenshot and will host drawing layers later."""

    def __init__(self, pixmap: QPixmap, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bg = pixmap

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        # Scale screenshot to fill the widget exactly, preserving sharpness
        painter.drawPixmap(self.rect(), self._bg, self._bg.rect())


class AnnotationCanvas(QMainWindow):
    """
    Fullscreen borderless window that shows the captured screenshot as background.

    Keyboard shortcuts
    ------------------
    Escape  — close / discard
    """

    def __init__(self, screenshot_path: str) -> None:
        super().__init__()
        self._screenshot_path = screenshot_path
        self._setup_window()
        self._load_screenshot()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _setup_window(self) -> None:
        self.setWindowTitle("WaySnap")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        # Cursor stays as default arrow; will switch to crosshair when drawing is added
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def _load_screenshot(self) -> None:
        pixmap = QPixmap(self._screenshot_path)
        if pixmap.isNull():
            # Fallback: gray canvas so the window is still usable for debugging
            screen = QApplication.primaryScreen()
            size = screen.size() if screen else self.size()
            pixmap = QPixmap(size)
            pixmap.fill(Qt.GlobalColor.darkGray)

        canvas_widget = _CanvasWidget(pixmap, self)
        self.setCentralWidget(canvas_widget)

        # Resize to the screen that contains the cursor so multi-monitor works
        screen = QApplication.screenAt(self.pos()) or QApplication.primaryScreen()
        if screen:
            self.setGeometry(screen.geometry())

        self.showFullScreen()

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)
