import enum
import logging

from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor, QCursor, QFont, QKeyEvent, QMouseEvent,
    QPaintEvent, QPainter, QPen,
)
from PyQt6.QtWidgets import QApplication, QWidget

log = logging.getLogger(__name__)

# ── Visual ────────────────────────────────────────────────────────────────────
_DIM_ALPHA  = 110               # darkness of the area OUTSIDE the selection
_BORDER_CLR = QColor("#00AAFF")
_BORDER_W   = 2
_HANDLE_R   = 5                 # visual radius (px)
_HANDLE_HIT = 9                 # hit-test radius (px) — bigger for easy grab
_HINT       = "Enter — сохранить  •  Esc — сбросить / закрыть"


class _H(enum.IntEnum):
    """Eight resize handles in clockwise order starting from top-left."""
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
    Transparent fullscreen overlay for region selection.

    The user sees the live desktop through the window.  After the region is
    confirmed the widget emits region_confirmed(QRect) and closes — the actual
    screenshot capture happens in TrayIconManager AFTER this window is gone.

    Keyboard
    --------
    Enter / Space  — confirm selection
    Escape         — clear selection; second Escape closes
    """

    region_confirmed = pyqtSignal(QRect)  # widget-space coords

    def __init__(self) -> None:
        super().__init__()

        self._sel   = QRect()
        self._state = "idle"           # idle | dragging | selected | resizing | moving

        self._drag_start    = QPoint()
        self._resize_handle = _H.NONE
        self._resize_origin = QRect()
        self._move_anchor   = QPoint()
        self._move_origin   = QRect()

        self._setup_window()

    # ── Init ──────────────────────────────────────────────────────────────────

    def _setup_window(self) -> None:
        self.setWindowTitle("WaySnap")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        # Transparent window: the live desktop shows through
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
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

        if sel.isEmpty():
            # No selection yet: very subtle dim so the user knows the overlay is active
            p.fillRect(self.rect(), QColor(0, 0, 0, 25))
        else:
            # 1. Start from fully transparent
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            p.fillRect(self.rect(), Qt.GlobalColor.transparent)

            # 2. Dim everything
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            p.fillRect(self.rect(), QColor(0, 0, 0, _DIM_ALPHA))

            # 3. Punch a transparent hole where the selection is (full brightness desktop)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            p.fillRect(sel, Qt.GlobalColor.transparent)

            # 4. Border + handles drawn on top
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            p.setPen(QPen(_BORDER_CLR, _BORDER_W))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(sel.adjusted(0, 0, -1, -1))

            p.setPen(QPen(Qt.GlobalColor.white, 1))
            p.setBrush(Qt.GlobalColor.white)
            for pt in _handle_points(sel):
                p.drawEllipse(pt, _HANDLE_R, _HANDLE_R)

            # 5. Size label
            self._paint_size_label(p, sel)

        # 6. Bottom-centre hint (always visible)
        self._paint_hint(p)

    def _paint_size_label(self, p: QPainter, sel: QRect) -> None:
        text = f"{sel.width()} × {sel.height()}"
        font = QFont("monospace", 10, QFont.Weight.Bold)
        p.setFont(font)
        fm = p.fontMetrics()
        tw, th = fm.horizontalAdvance(text), fm.height()
        pad = 5
        lx = max(0, sel.left())
        ly = sel.bottom() + pad + th
        if ly + pad > self.height():
            ly = sel.top() - pad
        p.fillRect(lx - 2, ly - th, tw + pad, th + pad, QColor(0, 0, 0, 180))
        p.setPen(Qt.GlobalColor.white)
        p.drawText(lx, ly, text)

    def _paint_hint(self, p: QPainter) -> None:
        font = QFont("sans-serif", 9)
        p.setFont(font)
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(_HINT)
        x = (self.width() - tw) // 2
        y = self.height() - 12
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
            delta = pos - self._move_anchor
            self._sel = _clamp_to_screen(self._move_origin.translated(delta), self.rect())
            self.update()
        else:
            self._refresh_cursor(pos)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._state in ("dragging", "resizing", "moving"):
            norm = self._sel.normalized()
            self._sel   = norm if (norm.width() >= 3 and norm.height() >= 3) else QRect()
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
                self._sel   = QRect()
                self._state = "idle"
                self.setCursor(Qt.CursorShape.CrossCursor)
                self.update()
            else:
                self.close()

    # ── Confirm ───────────────────────────────────────────────────────────────

    def _confirm(self) -> None:
        sel = self._sel.normalized()
        if sel.width() < 3 or sel.height() < 3:
            log.warning("Selection too small (%dx%d), ignoring", sel.width(), sel.height())
            return
        log.info("Region confirmed: %s", sel)
        self.region_confirmed.emit(sel)
        self.close()

    # ── Cursor ────────────────────────────────────────────────────────────────

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


# ── Module-level geometry helpers ─────────────────────────────────────────────

def _handle_points(r: QRect) -> list[QPoint]:
    cx, cy = r.center().x(), r.center().y()
    return [
        r.topLeft(),             # TL=0
        QPoint(cx, r.top()),     # T=1
        r.topRight(),            # TR=2
        QPoint(r.left(), cy),    # L=3
        QPoint(r.right(), cy),   # R=4
        r.bottomLeft(),          # BL=5
        QPoint(cx, r.bottom()),  # B=6
        r.bottomRight(),         # BR=7
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


def _clamp_to_screen(r: QRect, bounds: QRect) -> QRect:
    x = max(bounds.left(), min(r.x(), bounds.right()  - r.width()  + 1))
    y = max(bounds.top(),  min(r.y(), bounds.bottom() - r.height() + 1))
    return QRect(x, y, r.width(), r.height())
