import enum
import logging

from PyQt6.QtCore import QPoint, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor, QCursor, QFont, QIcon, QKeyEvent, QMouseEvent,
    QPaintEvent, QPainter, QPen, QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication, QButtonGroup, QColorDialog, QFrame,
    QHBoxLayout, QPushButton, QSpinBox, QWidget,
)

from .shapes import Shape, Stroke, make_shape

log = logging.getLogger(__name__)

# ── Visual constants ──────────────────────────────────────────────────────────
_DIM_ALPHA   = 110
_BORDER_CLR  = QColor("#00AAFF")
_BORDER_W    = 2
_HANDLE_R    = 5
_HANDLE_HIT  = 9
_DEFAULT_CLR = QColor("#FF3B30")
_DEFAULT_W   = 3


# ── Handle enum ───────────────────────────────────────────────────────────────
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


# ── Toolbar ───────────────────────────────────────────────────────────────────

class _Toolbar(QFrame):
    """Floating annotation toolbar shown at the top of the canvas."""

    tool_changed   = pyqtSignal(str)
    color_changed  = pyqtSignal(QColor)
    width_changed  = pyqtSignal(int)
    undo_requested = pyqtSignal()

    _TOOLS = [
        ("select",  "⬚", "Select  [S]"),
        ("pencil",  "✏", "Pencil  [P]"),
        ("arrow",   "↗", "Arrow   [A]"),
        ("rect",    "▭", "Rect    [R]"),
        ("ellipse", "⬭", "Ellipse [E]"),
    ]

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._color = QColor(_DEFAULT_CLR)
        self._build()
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def _build(self) -> None:
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 5, 8, 5)
        lay.setSpacing(3)

        self._btns: dict[str, QPushButton] = {}
        grp = QButtonGroup(self)
        grp.setExclusive(True)

        for tool_id, icon, tip in self._TOOLS:
            btn = QPushButton(icon)
            btn.setCheckable(True)
            btn.setFixedSize(34, 30)
            btn.setToolTip(tip)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            grp.addButton(btn)
            self._btns[tool_id] = btn
            lay.addWidget(btn)

        self._btns["select"].setChecked(True)
        grp.buttonClicked.connect(self._on_tool)

        lay.addWidget(self._sep())

        # Color
        self._color_btn = QPushButton()
        self._color_btn.setFixedSize(34, 30)
        self._color_btn.setToolTip("Color")
        self._color_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._color_btn.clicked.connect(self._pick_color)
        self._refresh_color()
        lay.addWidget(self._color_btn)

        # Width
        self._w_spin = QSpinBox()
        self._w_spin.setRange(1, 20)
        self._w_spin.setValue(_DEFAULT_W)
        self._w_spin.setFixedWidth(50)
        self._w_spin.setToolTip("Line width")
        self._w_spin.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._w_spin.valueChanged.connect(self.width_changed.emit)
        lay.addWidget(self._w_spin)

        lay.addWidget(self._sep())

        # Undo
        undo = QPushButton("↩")
        undo.setFixedSize(34, 30)
        undo.setToolTip("Undo  [Ctrl+Z]")
        undo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        undo.clicked.connect(self.undo_requested.emit)
        lay.addWidget(undo)

        self.setStyleSheet("""
            _Toolbar, QFrame#toolbar {
                background: rgba(24,24,24,215);
                border: 1px solid rgba(255,255,255,25);
                border-radius: 8px;
            }
            QPushButton {
                background: transparent; color: white;
                border: none; border-radius: 4px; font-size: 15px;
            }
            QPushButton:hover   { background: rgba(255,255,255,18); }
            QPushButton:checked { background: #2979FF; }
            QSpinBox {
                background: rgba(255,255,255,12); color: white;
                border: 1px solid rgba(255,255,255,20); border-radius: 3px;
                padding: 1px 3px;
            }
            QSpinBox::up-button, QSpinBox::down-button { width: 14px; }
        """)
        self.setObjectName("toolbar")
        self.adjustSize()

    @staticmethod
    def _sep() -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.Shape.VLine)
        f.setStyleSheet("background: rgba(255,255,255,25); max-width:1px; margin:3px 2px;")
        f.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return f

    def _on_tool(self, btn: QPushButton) -> None:
        for tid, b in self._btns.items():
            if b is btn:
                self.tool_changed.emit(tid)
                return

    def _pick_color(self) -> None:
        c = QColorDialog.getColor(self._color, self, "Pick colour")
        if c.isValid():
            self._color = c
            self._refresh_color()
            self.color_changed.emit(c)

    def _refresh_color(self) -> None:
        px = QPixmap(18, 18)
        px.fill(self._color)
        self._color_btn.setIcon(QIcon(px))
        self._color_btn.setIconSize(QSize(18, 18))

    def select_tool(self, tool_id: str) -> None:
        if btn := self._btns.get(tool_id):
            btn.setChecked(True)

    @property
    def color(self) -> QColor:
        return QColor(self._color)

    @property
    def pen_width(self) -> int:
        return self._w_spin.value()


# ── Canvas ────────────────────────────────────────────────────────────────────

class AnnotationCanvas(QWidget):
    """
    Fullscreen overlay: frozen screenshot as background, region selector,
    drawing tools (pencil / arrow / rect / ellipse), toolbar.

    On confirm the canvas composites background + annotations and emits
    region_confirmed(QPixmap) — TrayIconManager saves and copies it.

    Keyboard shortcuts
    ------------------
    S / P / A / R / E   — switch tool
    Ctrl+Z              — undo last shape
    Enter / Space       — confirm (requires a selection)
    Esc                 — clear selection (first press) / close (second press)
    """

    region_confirmed = pyqtSignal(QPixmap)

    def __init__(self, screenshot_path: str, target_screen=None) -> None:
        super().__init__()
        self._bg            = self._load_pixmap(screenshot_path)
        self._target_screen = target_screen

        # ── Selection state ───────────────────────────────────────────────────
        self._sel   = QRect()
        self._state = "idle"   # idle | dragging | selected | resizing | moving
        self._drag_start    = QPoint()
        self._resize_handle = _H.NONE
        self._resize_origin = QRect()
        self._move_anchor   = QPoint()
        self._move_origin   = QRect()

        # ── Drawing state ─────────────────────────────────────────────────────
        self._tool    = "select"
        self._shapes:  list[Shape] = []
        self._current: Shape | None = None
        self._pen_color = QColor(_DEFAULT_CLR)
        self._pen_width = _DEFAULT_W

        self._setup_window()

        # Toolbar (child widget — floats on top)
        self._toolbar = _Toolbar(self)
        self._toolbar.tool_changed.connect(self._set_tool)
        self._toolbar.color_changed.connect(self._set_color)
        self._toolbar.width_changed.connect(self._set_width)
        self._toolbar.undo_requested.connect(self._undo)
        self._position_toolbar()

    # ── Init ──────────────────────────────────────────────────────────────────

    def _load_pixmap(self, path: str) -> QPixmap:
        px = QPixmap(path)
        if not px.isNull():
            log.debug("Background: %d×%d", px.width(), px.height())
            return px
        log.error("Cannot load %s — gray fallback", path)
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

        screen = (self._target_screen
                  or QApplication.screenAt(QCursor.pos())
                  or QApplication.primaryScreen())
        if screen:
            self.setGeometry(screen.geometry())

        self.showFullScreen()
        self.activateWindow()
        self.raise_()

    def _position_toolbar(self) -> None:
        self._toolbar.adjustSize()
        x = (self.width() - self._toolbar.width()) // 2
        self._toolbar.move(x, 16)
        self._toolbar.raise_()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if hasattr(self, "_toolbar"):
            self._position_toolbar()

    # ── Tool management ───────────────────────────────────────────────────────

    def _set_tool(self, tool: str) -> None:
        self._tool = tool
        self._current = None
        if tool == "select":
            self._refresh_cursor(QCursor.pos() - self.pos())
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocus()
        self.update()

    def _set_color(self, color: QColor) -> None:
        self._pen_color = color

    def _set_width(self, width: int) -> None:
        self._pen_width = width

    def _undo(self) -> None:
        if self._shapes:
            self._shapes.pop()
            self.update()

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        p = QPainter(self)
        sel = self._sel.normalized()

        # 1. Background screenshot
        p.drawPixmap(self.rect(), self._bg, self._bg.rect())

        if not sel.isEmpty():
            # 2. Dim outside selection
            p.fillRect(self.rect(), QColor(0, 0, 0, _DIM_ALPHA))
            # 3. Restore selection at full brightness
            p.drawPixmap(sel, self._bg, self._widget_to_bg(sel))
            # 4. Selection border + handles (only in select tool)
            if self._tool == "select":
                p.setPen(QPen(_BORDER_CLR, _BORDER_W))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(sel.adjusted(0, 0, -1, -1))
                p.setPen(QPen(Qt.GlobalColor.white, 1))
                p.setBrush(Qt.GlobalColor.white)
                for pt in _handle_points(sel):
                    p.drawEllipse(pt, _HANDLE_R, _HANDLE_R)
            else:
                # Faint dashed border when drawing
                pen = QPen(_BORDER_CLR, 1, Qt.PenStyle.DashLine)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(sel.adjusted(0, 0, -1, -1))

        # 5. Completed shapes
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for shape in self._shapes:
            shape.draw(p)

        # 6. Shape being drawn right now
        if self._current is not None:
            self._current.draw(p)

        # 7. Size label + hint
        if not sel.isEmpty():
            self._paint_size_label(p, sel)
        self._paint_hint(p)

    def _paint_size_label(self, p: QPainter, sel: QRect) -> None:
        src  = self._widget_to_bg(sel)
        text = f"{src.width()} × {src.height()}"
        font = QFont("monospace", 10, QFont.Weight.Bold)
        p.setFont(font)
        fm = p.fontMetrics()
        tw, th = fm.horizontalAdvance(text), fm.height()
        lx = max(0, sel.left())
        ly = sel.bottom() + 5 + th
        if ly + 5 > self.height():
            ly = sel.top() - 5
        p.fillRect(lx - 2, ly - th, tw + 7, th + 5, QColor(0, 0, 0, 180))
        p.setPen(Qt.GlobalColor.white)
        p.drawText(lx, ly, text)

    def _paint_hint(self, p: QPainter) -> None:
        if self._tool == "select":
            text = "S/P/A/R/E — tools  •  Enter — save  •  Esc — reset / close"
        else:
            tool_names = {"pencil": "Pencil", "arrow": "Arrow",
                          "rect": "Rect", "ellipse": "Ellipse"}
            name = tool_names.get(self._tool, self._tool)
            text = f"{name}  •  Ctrl+Z — undo  •  Enter — save  •  Esc — close"
        font = QFont("sans-serif", 9)
        p.setFont(font)
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(text)
        x  = (self.width() - tw) // 2
        y  = self.height() - 12
        p.fillRect(x - 6, y - fm.height(), tw + 12, fm.height() + 6,
                   QColor(0, 0, 0, 160))
        p.setPen(QColor(200, 200, 200))
        p.drawText(x, y, text)

    # ── Mouse ─────────────────────────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.pos()

        # Don't draw if click is inside the toolbar
        if self._toolbar.geometry().contains(pos):
            return

        if self._tool == "select":
            self._press_select(pos)
        else:
            self._press_draw(pos)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.pos()
        if self._tool == "select":
            self._move_select(pos)
        else:
            self._move_draw(pos)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.pos()
        if self._tool == "select":
            self._release_select(pos)
        else:
            self._release_draw()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._confirm()

    # ── Select-tool mouse ─────────────────────────────────────────────────────

    def _press_select(self, pos: QPoint) -> None:
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

    def _move_select(self, pos: QPoint) -> None:
        if self._state == "dragging":
            self._sel = QRect(self._drag_start, pos)
            self.update()
        elif self._state == "resizing":
            self._sel = _apply_resize(self._resize_origin, self._resize_handle, pos)
            self.update()
        elif self._state == "moving":
            self._sel = _clamp(self._move_origin.translated(pos - self._move_anchor),
                               self.rect())
            self.update()
        else:
            self._refresh_cursor(pos)

    def _release_select(self, pos: QPoint) -> None:
        if self._state in ("dragging", "resizing", "moving"):
            norm = self._sel.normalized()
            self._sel   = norm if norm.width() >= 3 and norm.height() >= 3 else QRect()
            self._state = "selected" if not self._sel.isEmpty() else "idle"
            self._refresh_cursor(pos)
            self.update()

    # ── Drawing-tool mouse ────────────────────────────────────────────────────

    def _press_draw(self, pos: QPoint) -> None:
        self._current = make_shape(self._tool, self._pen_color, self._pen_width)
        if isinstance(self._current, Stroke):
            self._current.points.append(pos)
        else:
            self._current.start = pos
            self._current.end   = pos

    def _move_draw(self, pos: QPoint) -> None:
        if self._current is None:
            return
        if isinstance(self._current, Stroke):
            self._current.points.append(pos)
        else:
            self._current.end = pos
        self.update()

    def _release_draw(self) -> None:
        if self._current is not None and self._current.is_valid():
            self._shapes.append(self._current)
        self._current = None
        self.update()

    # ── Keyboard ──────────────────────────────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        k   = event.key()
        mod = event.modifiers()

        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self._confirm()
        elif k == Qt.Key.Key_Escape:
            if self._shapes:
                # First ESC clears drawings
                self._shapes.clear()
                self._current = None
                self.update()
            elif self._state != "idle":
                self._sel, self._state = QRect(), "idle"
                self.setCursor(Qt.CursorShape.CrossCursor)
                self.update()
            else:
                self.close()
        elif mod == Qt.KeyboardModifier.ControlModifier and k == Qt.Key.Key_Z:
            self._undo()
        # Tool shortcuts
        elif k == Qt.Key.Key_S:
            self._set_tool("select");  self._toolbar.select_tool("select")
        elif k == Qt.Key.Key_P:
            self._set_tool("pencil");  self._toolbar.select_tool("pencil")
        elif k == Qt.Key.Key_A:
            self._set_tool("arrow");   self._toolbar.select_tool("arrow")
        elif k == Qt.Key.Key_R:
            self._set_tool("rect");    self._toolbar.select_tool("rect")
        elif k == Qt.Key.Key_E:
            self._set_tool("ellipse"); self._toolbar.select_tool("ellipse")
        else:
            super().keyPressEvent(event)

    # ── Confirm ───────────────────────────────────────────────────────────────

    def _confirm(self) -> None:
        sel = self._sel.normalized()
        if sel.width() < 3 or sel.height() < 3:
            log.warning("No region selected — cannot save")
            return
        pixmap = self._composite(sel)
        log.info("Confirmed: %d×%d px", pixmap.width(), pixmap.height())
        self.region_confirmed.emit(pixmap)
        self.close()

    def _composite(self, sel: QRect) -> QPixmap:
        """
        Render background crop + all annotations into a single QPixmap.
        Shapes are stored in widget coords; they're scaled to physical pixels.
        """
        src    = self._widget_to_bg(sel)
        output = QPixmap(src.size())
        output.fill(Qt.GlobalColor.transparent)

        p = QPainter(output)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 1. Background crop at full physical resolution
        p.drawPixmap(0, 0, self._bg, src.x(), src.y(), src.width(), src.height())

        # 2. Scale painter so widget-space shapes land on physical pixels
        sx = src.width()  / sel.width()
        sy = src.height() / sel.height()
        p.scale(sx, sy)
        p.translate(-sel.x(), -sel.y())

        # 3. Draw all finished shapes
        for shape in self._shapes:
            shape.draw(p)

        p.end()
        return output

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _widget_to_bg(self, r: QRect) -> QRect:
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
