import logging

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCursor, QKeyEvent, QPaintEvent, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QWidget

log = logging.getLogger(__name__)


class AnnotationCanvas(QWidget):
    """
    Fullscreen borderless overlay with the captured screenshot as background.

    Using QWidget (not QMainWindow) deliberately: QMainWindow silently adds
    QSizeGrip widgets in the bottom corners and wraps the central widget in
    toolbar/statusbar layout regions — both produce visible artifacts when the
    window is frameless and fullscreen.

    Keyboard shortcuts
    ------------------
    Escape — close / discard
    """

    def __init__(self, screenshot_path: str) -> None:
        super().__init__()
        self._bg: QPixmap = self._load_pixmap(screenshot_path)
        self._setup_window()

    # ------------------------------------------------------------------
    # Init helpers
    # ------------------------------------------------------------------

    def _load_pixmap(self, path: str) -> QPixmap:
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            log.debug("Loaded screenshot: %dx%d px from %s", pixmap.width(), pixmap.height(), path)
            return pixmap

        log.error("QPixmap could not load %s — using gray fallback", path)
        screen = QApplication.primaryScreen()
        size = screen.size() if screen else None
        fallback = QPixmap(size) if size else QPixmap(1920, 1080)
        fallback.fill(Qt.GlobalColor.darkGray)
        return fallback

    def _setup_window(self) -> None:
        self.setWindowTitle("WaySnap")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setCursor(Qt.CursorShape.ArrowCursor)

        # Use the screen that currently holds the mouse cursor.
        # QCursor.pos() is reliable here; self.pos() is (0,0) before first show.
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen:
            self.setGeometry(screen.geometry())
            log.debug("Canvas geometry set to %s", screen.geometry())

        self.showFullScreen()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        # drawPixmap(target_rect, pixmap, source_rect) — scales the screenshot
        # to fill the entire widget without stretching artifacts.
        painter.drawPixmap(self.rect(), self._bg, self._bg.rect())

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)
