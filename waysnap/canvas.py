import enum
import logging

from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import (
    QColor, QCursor, QFont, QKeyEvent, QMouseEvent,
    QPaintEvent, QPainter, QPen, QPixmap,
)
from PyQt6.QtWidgets import QApplication, QWidget

log = logging.getLogger(__name__)

# ── Visual ────────────────────────────────────────────────────────────────────
_OVERLAY_ALPHA  = 160               # darkness outside selection (0-255)
_BORDER_CLR     = QColor("#00AAFF")
_BORDER_W       = 2
_HANDLE_R       = 5                 # visual radius of handle dots (px)
_HANDLE_HIT_R   = 9                 # hit-test radius — bigger for easy grabbing
_DIM            = QColor(0, 0, 0, _OVERLAY_ALPHA)
_HINT_TEXT      = "Enter — сохранить  •  Esc — отменить выделение / закрыть"


# ── Handle enum ───────────────────────────────────────────────────────────────
#   TL  T  TR
#   L       R
#   BL  B  BR
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
    Fullscreen overlay: shows the screenshot dimmed, lets the user drag out
    a selection rectangle, resize it via 8 handles, and confirm with Enter.

    Using QWidget directly (not QMainWindow) to avoid invisible toolbar/
    statusbar regions and the QSizeGrip corner widgets that QMainWindow adds.

    Keyboard
    --------
    Enter / Space  — save selection to /tmp/waysnap_region.png + clipboard
    Escape         — clear selection; second press closes
    """

    def __init__(self, screenshot_path: str) -> None:
        super().__init__()
        self._bg: QPixmap = self._load_pixmap(screenshot_path)

        # Selection geometry (screen/widget coords, may be un-normalised during drag)
        self._sel = QRect()

        # State machine: idle → dragging → selected ↔ resizing / moving
        self._state = "idle"
        self._drag_start   = QPoint()   # origin of current new-selection drag
        self._resize_handle = _H.NONE
        self._resize_origin = QRect()   # _sel snapshot at resize-start
        self._move_anchor  = QPoint()   # cursor pos at move-start
        self._move_origin  = QRect()    # _sel snapshot at move-start

        self._setup_window()

    # ── Init ──────────────────────────────────────────────────────────────────

    def _load_pixmap(self, path: str) -> QPixmap:
        px = QPixmap(path)
        if not px.isNull():
            log.debug("Screenshot loaded: %d×%d from %s", px.width(), px.height(), path)
            return px
        log.error("Cannot load %s — falling back to gray", path)
        screen = QApplication.primaryScreen()
        fb = QPixmap(screen.size() if screen else QPixmap(1920, 1080))
        fb.fill(Qt.GlobalColor.darkGray)
        return fb

    def _setup_window(self) -> None:
        self.setWindowTitle("WaySnap")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        # Tell Qt that paintEvent covers the entire widget so it must not
        # pre-fill with the background colour before calling paintEvent.
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMouseTracking(True)   # cursor updates even without button held
        self.setCursor(Qt.CursorShape.CrossCursor)

        # Put the window on the screen where the cursor currently is
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen:
            self.setGeometry(screen.geometry())

        self.showFullScreen()

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        p = QPainter(self)

        # 1. Full screenshot as base layer
        p.drawPixmap(self.rect(), self._bg, self._bg.rect())

        sel = self._sel.normalized()

        if not sel.isEmpty():
            # 2. Dark overlay over everything
            p.fillRect(self.rect(), _DIM)

            # 3. Reveal screenshot inside selection at full brightness
            p.drawPixmap(sel, self._bg, self._screen_to_px(sel))

            # 4. Selection border
            p.setPen(QPen(_BORDER_CLR, _BORDER_W))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(sel.adjusted(0, 0, -1, -1))

            # 5. Eight resize handles
            p.setPen(QPen(Qt.GlobalColor.white, 1))
            p.setBrush(Qt.GlobalColor.white)
            for pt in _handle_points(sel):
                p.drawEllipse(pt, _HANDLE_R, _HANDLE_R)

            # 6. Pixel-size label just below (or above) the selection
            self._paint_size_label(p, sel)

        # 7. Bottom-centre hint
        self._paint_hint(p)

    def _paint_size_label(self, p: QPainter, sel: QRect) -> None:
        # Map widget coords → pixmap pixels for the "real" size
        src = self._screen_to_px(sel)
        text = f"{src.width()} × {src.height()}"

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
        tw = fm.horizontalAdvance(_HINT_TEXT)
        x = (self.width() - tw) // 2
        y = self.height() - 12
        p.fillRect(x - 6, y - fm.height(), tw + 12, fm.height() + 6, QColor(0, 0, 0, 160))
        p.setPen(QColor(200, 200, 200))
        p.drawText(x, y, _HINT_TEXT)

    # ── Mouse ─────────────────────────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.pos()

        if self._state == "selected":
            h = _hit_handle(pos, self._sel.normalized())
            if h != _H.NONE:
                # Begin resize from a handle
                self._resize_handle = h
                self._resize_origin = QRect(self._sel.normalized())
                self._state = "resizing"
                return
            if self._sel.normalized().contains(pos):
                # Begin move
                self._move_anchor = pos
                self._move_origin = QRect(self._sel.normalized())
                self._state = "moving"
                return

        # Start a brand-new selection drag
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
            # idle / selected — just update the cursor shape
            self._refresh_cursor(pos)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._state in ("dragging", "resizing", "moving"):
            norm = self._sel.normalized()
            if norm.width() >= 3 and norm.height() >= 3:
                self._sel = norm
                self._state = "selected"
            else:
                self._sel = QRect()
                self._state = "idle"
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
                self._sel = QRect()
                self._state = "idle"
                self.setCursor(Qt.CursorShape.CrossCursor)
                self.update()
            else:
                self.close()

    # ── Confirm ───────────────────────────────────────────────────────────────

    def _confirm(self) -> None:
        sel = self._sel.normalized()
        if sel.width() < 3 or sel.height() < 3:
            log.warning("Selection too small to save (%dx%d)", sel.width(), sel.height())
            return

        src = self._screen_to_px(sel)
        cropped = self._bg.copy(src)

        out = "/tmp/waysnap_region.png"
        cropped.save(out, "PNG")
        log.info("Saved: %d×%d px → %s", src.width(), src.height(), out)

        QApplication.clipboard().setPixmap(cropped)
        log.info("Copied to clipboard")

        self.close()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _screen_to_px(self, r: QRect) -> QRect:
        """Map a widget-space rect to pixmap pixel coordinates (handles HiDPI)."""
        sx = self._bg.width()  / self.width()
        sy = self._bg.height() / self.height()
        return QRect(
            int(r.x() * sx), int(r.y() * sy),
            max(1, int(r.width()  * sx)),
            max(1, int(r.height() * sy)),
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


# ── Module-level geometry helpers (stateless, easier to test) ─────────────────

def _handle_points(r: QRect) -> list[QPoint]:
    """8 handle positions for a normalised rect, in _H enum order."""
    cx, cy = r.center().x(), r.center().y()
    return [
        r.topLeft(),              # TL=0
        QPoint(cx, r.top()),      # T=1
        r.topRight(),             # TR=2
        QPoint(r.left(), cy),     # L=3
        QPoint(r.right(), cy),    # R=4
        r.bottomLeft(),           # BL=5
        QPoint(cx, r.bottom()),   # B=6
        r.bottomRight(),          # BR=7
    ]


def _hit_handle(pos: QPoint, r: QRect) -> _H:
    """Return the handle under *pos*, or _H.NONE."""
    if r.isEmpty():
        return _H.NONE
    for i, pt in enumerate(_handle_points(r)):
        if (pos - pt).manhattanLength() <= _HANDLE_HIT_R * 2:
            return _H(i)
    return _H.NONE


def _apply_resize(origin: QRect, handle: _H, pos: QPoint) -> QRect:
    """
    Return a new rect by moving the edge(s) indicated by *handle* to *pos*.
    Works on a copy of *origin* so the opposite edges stay fixed.
    Result may be un-normalised (negative size) — caller normalises on release.
    """
    r = QRect(origin)
    if handle in (_H.TL, _H.L, _H.BL): r.setLeft(pos.x())
    if handle in (_H.TR, _H.R, _H.BR): r.setRight(pos.x())
    if handle in (_H.TL, _H.T, _H.TR): r.setTop(pos.y())
    if handle in (_H.BL, _H.B, _H.BR): r.setBottom(pos.y())
    return r


def _clamp_to_screen(r: QRect, bounds: QRect) -> QRect:
    """Translate *r* so it stays within *bounds* without changing its size."""
    x = max(bounds.left(), min(r.x(), bounds.right()  - r.width()  + 1))
    y = max(bounds.top(),  min(r.y(), bounds.bottom() - r.height() + 1))
    return QRect(x, y, r.width(), r.height())
