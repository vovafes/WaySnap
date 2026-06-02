import enum
import logging

from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor, QCursor, QFont, QKeyEvent, QMouseEvent,
    QPaintEvent, QPainter, QPen, QPixmap,
)
from PyQt6.QtWidgets import QApplication, QWidget

log = logging.getLogger(__name__)

_DIM_ALPHA  = 110
_BORDER_CLR = QColor("#00AAFF")
_BORDER_W   = 2
_HANDLE_R   = 5
_HANDLE_HIT = 9
_HINT       = "Enter — сохранить  •  Esc — сбросить / закрыть"


class _H(enum.IntEnum):
    NONE = -1
    TL=0; T=1; TR=2
    L=3;       R=4
    BL=5; B=6; BR=7


_CURSORS: dict[_H, Qt.CursorShape] = {
    _H.TL: Qt.CursorShape.SizeFDiagCursor,
    _H.T:  Qt.CursorShape.SizeVerCursor,
    _H.TR: Qt.CursorShape.SizeBDiagCursor,
    _H.L:  Qt.CursorShape.SizeHorCursor,
    _H.R:  Qt.CursorShape.SizeHorCursor,
    _H.BL: Qt.CursorShape.SizeBDiagCursor,
    _H.B:  Qt.CursorShape.SizeVerCursor,
    _H.BR: Qt.CursorShape.SizeFDiagCursor,
}


class AnnotationCanvas(QWidget):
    """
    Fullscreen overlay that shows the captured screenshot as a frozen background.
    The user drags a selection rectangle; on Enter the selected region is emitted.

    Flow: TrayIconManager captures the screen FIRST, then opens this canvas.
    We avoid transparent windows entirely — Qt6/Wayland transparency is unreliable.

    Signals
    -------
    region_confirmed(QRect)  — widget-space selection, emitted on confirm
    """

    region_confirmed = pyqtSignal(QRect)

    def __init__(self, screenshot_path: str) -> None:
        super().__init__()
        self._bg = self._load_pixmap(screenshot_path)

        self._sel   = QRect()
        self._state = "idle"

        self._drag_start    = QPoint()
        self._resize_handle = _H.NONE
        self._resize_origin = QRect()
        self._move_anchor   = QPoint()
        self._move_origin   = QRect()

        self._setup_window()

    # ── Init ──────────────────────────────────────────────────────────────────

    def _load_pixmap(self, path: str) -> QPixmap:
        px = QPixmap(path)
        if not px.isNull():
            log.debug("Background loaded: %d×%d", px.width(), px.height())
            return px
        log.error("Cannot load %s — using gray fallback", path)
        screen = QApplication.primaryScreen()
        fb = QPixmap(screen.size() if screen else QPixmap(1920, 1080).size())
        fb.fill(Qt.GlobalColor.darkGray)
        return fb

    def _setup_window(self) -> None:
        self.setWindowTitle("WaySnap")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen:
            self.setGeometry(screen.geometry())

        self.showFullScreen()
        self.activateWindow()
        self.raise_()

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        p = QPainter(self)
        sel = self._sel.normalized()

        # 1. Full screenshot fills the entire widget
        p.drawPixmap(self.rect(), self._bg, self._bg.rect())

        if not sel.isEmpty():
            # 2. Dim everything outside the selection
            p.fillRect(self.rect(), QColor(0, 0, 0, _DIM_ALPHA))

            # 3. Restore screenshot at full brightness inside selection
            p.drawPixmap(sel, self._bg, self._widget_to_bg(sel))

            # 4. Border
            p.setPen(QPen(_BORDER_CLR, _BORDER_W))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(sel.adjusted(0, 0, -1, -1))

            # 5. Handles
            p.setPen(QPen(Qt.GlobalColor.white, 1))
            p.setBrush(Qt.GlobalColor.white)
            for pt in _handle_points(sel):
                p.drawEllipse(pt, _HANDLE_R, _HANDLE_R)

            # 6. Size label
            self._paint_size_label(p, sel)

        # 7. Bottom hint
        self._paint_hint(p)

    def _paint_size_label(self, p: QPainter, sel: QRect) -> None:
        src  = self._widget_to_bg(sel)
        text = f"{src.width()} × {src.height()}"
        font = QFont("monospace", 10, QFont.Weight.Bold)
        p.setFont(font)
        fm   = p.fontMetrics()
        tw, th = fm.horizontalAdvance(text), fm.height()
        lx = max(0, sel.left())
        ly = sel.bottom() + 5 + th
        if ly + 5 > self.height():
            ly = sel.top() - 5
        p.fillRect(lx - 2, ly - th, tw + 7, th + 5, QColor(0, 0, 0, 180))
        p.setPen(Qt.GlobalColor.white)
        p.drawText(lx, ly, text)

    def _paint_hint(self, p: QPainter) -> None:
        font = QFont("sans-serif", 9)
        p.setFont(font)
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(_HINT)
        x  = (self.width() - tw) // 2
        y  = self.height() - 12
        p.fillRect(x - 6, y - fm.height(), tw + 12, fm.height() + 6, QColor(0, 0, 0, 160))
        p.setPen(QColor(200, 200, 200))
        p.drawText(x, y, _HINT)

    # ── Mouse ─────────────────────────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.pos()
        if self._state == "selected":
            h = _hit_handle(pos, self._sel.normalized())
            if h != _H.NONE:
                self._resize_handle = h
                self._resize_origin = QRect(self._sel.normalized())
                self._state = "resizing"
                return
            if self._sel.normalized().contains(pos):
                self._move_anchor = pos
                self._move_origin = QRect(self._sel.normalized())
                self._state = "moving"
                return
        self._drag_start = pos
        self._sel = QRect(pos, pos)
        self._state = "dragging"
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.pos()
        if self._state == "dragging":
            self._sel = QRect(self._drag_start, pos)
            self.update()
        elif self._state == "resizing":
            self._sel = _apply_resize(self._resize_origin, self._resize_handle, pos)
            self.update()
        elif self._state == "moving":
            self._sel = _clamp(self._move_origin.translated(pos - self._move_anchor), self.rect())
            self.update()
        else:
            self._refresh_cursor(pos)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._state in ("dragging", "resizing", "moving"):
            norm = self._sel.normalized()
            self._sel   = norm if norm.width() >= 3 and norm.height() >= 3 else QRect()
            self._state = "selected" if not self._sel.isEmpty() else "idle"
            self._refresh_cursor(event.pos())
            self.update()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._confirm()

    # ── Keyboard ──────────────────────────────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        k = event.key()
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self._confirm()
        elif k == Qt.Key.Key_Escape:
            if self._state != "idle":
                self._sel, self._state = QRect(), "idle"
                self.setCursor(Qt.CursorShape.CrossCursor)
                self.update()
            else:
                self.close()

    # ── Confirm ───────────────────────────────────────────────────────────────

    def _confirm(self) -> None:
        sel = self._sel.normalized()
        if sel.width() < 3 or sel.height() < 3:
            return
        log.info("Region confirmed: %s", sel)
        self.region_confirmed.emit(sel)
        self.close()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _widget_to_bg(self, r: QRect) -> QRect:
        """Map widget-space rect to background pixmap pixel coords (HiDPI-aware)."""
        sx = self._bg.width()  / self.width()
        sy = self._bg.height() / self.height()
        return QRect(
            int(r.x() * sx), int(r.y() * sy),
            max(1, int(r.width() * sx)), max(1, int(r.height() * sy)),
        )

    def _refresh_cursor(self, pos: QPoint) -> None:
        if not self._sel.isEmpty():
            h = _hit_handle(pos, self._sel.normalized())
            if h != _H.NONE:
                self.setCursor(_CURSORS[h])
                return
            if self._sel.normalized().contains(pos):
                self.setCursor(Qt.CursorShape.SizeAllCursor)
                return
        self.setCursor(Qt.CursorShape.CrossCursor)


# ── Geometry helpers ──────────────────────────────────────────────────────────

def _handle_points(r: QRect) -> list[QPoint]:
    cx, cy = r.center().x(), r.center().y()
    return [
        r.topLeft(), QPoint(cx, r.top()), r.topRight(),
        QPoint(r.left(), cy),             QPoint(r.right(), cy),
        r.bottomLeft(), QPoint(cx, r.bottom()), r.bottomRight(),
    ]


def _hit_handle(pos: QPoint, r: QRect) -> _H:
    if r.isEmpty():
        return _H.NONE
    for i, pt in enumerate(_handle_points(r)):
        if (pos - pt).manhattanLength() <= _HANDLE_HIT * 2:
            return _H(i)
    return _H.NONE


def _apply_resize(origin: QRect, handle: _H, pos: QPoint) -> QRect:
    r = QRect(origin)
    if handle in (_H.TL, _H.L, _H.BL): r.setLeft(pos.x())
    if handle in (_H.TR, _H.R, _H.BR): r.setRight(pos.x())
    if handle in (_H.TL, _H.T, _H.TR): r.setTop(pos.y())
    if handle in (_H.BL, _H.B, _H.BR): r.setBottom(pos.y())
    return r


def _clamp(r: QRect, bounds: QRect) -> QRect:
    x = max(bounds.left(), min(r.x(), bounds.right()  - r.width()  + 1))
    y = max(bounds.top(),  min(r.y(), bounds.bottom() - r.height() + 1))
    return QRect(x, y, r.width(), r.height())
