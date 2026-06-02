import os
import shutil
import subprocess

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .canvas import AnnotationCanvas

SCREENSHOT_PATH = "/tmp/waysnap_shot.png"
CAPTURE_DELAY_MS = 300  # ms to wait after hiding menu so it disappears from screen

# Pixels sampled for black-screen detection (row_fraction, col_fraction)
_SAMPLE_GRID = [
    (0.25, 0.25), (0.25, 0.50), (0.25, 0.75),
    (0.50, 0.25), (0.50, 0.50), (0.50, 0.75),
    (0.75, 0.25), (0.75, 0.50), (0.75, 0.75),
]
# Wayland security blocks grabWindow by returning a fully-black image;
# any pixel above this threshold means the grab actually worked.
_BLACK_THRESHOLD = 5


class TrayIconManager(QSystemTrayIcon):
    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self._app = app
        self._canvas: AnnotationCanvas | None = None

        self.setIcon(self._make_placeholder_icon())
        self.setToolTip("WaySnap — нажмите для скриншота")

        self._build_menu()

        # Single click on tray icon also triggers screenshot
        self.activated.connect(self._on_activated)

    # ------------------------------------------------------------------
    # Icon
    # ------------------------------------------------------------------

    def _make_placeholder_icon(self) -> QIcon:
        """Blue 32×32 square with 'WS' text — placeholder until real icon is added."""
        pixmap = QPixmap(32, 32)
        pixmap.fill(QColor("#2979FF"))

        painter = QPainter(pixmap)
        painter.setPen(QColor("white"))
        font = QFont("Arial", 10, QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "WS")
        painter.end()

        return QIcon(pixmap)

    # ------------------------------------------------------------------
    # Menu
    # ------------------------------------------------------------------

    def _build_menu(self) -> None:
        menu = QMenu()

        act_shot = menu.addAction("Сделать скриншот")
        act_shot.triggered.connect(self._trigger_screenshot)

        menu.addSeparator()

        act_exit = menu.addAction("Выход")
        act_exit.triggered.connect(self._app.quit)

        self.setContextMenu(menu)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._trigger_screenshot()

    # ------------------------------------------------------------------
    # Screenshot pipeline
    # ------------------------------------------------------------------

    def _trigger_screenshot(self) -> None:
        if menu := self.contextMenu():
            menu.hide()
        QTimer.singleShot(CAPTURE_DELAY_MS, self._capture_screen)

    def _capture_screen(self) -> None:
        """Try capture methods in priority order; open canvas on first success."""
        methods = [
            self._capture_via_qt,         # X11 + some Wayland compositors
            self._capture_via_dbus_gnome,  # GNOME Wayland (Ubuntu, Fedora, etc.)
            self._capture_via_grim,        # wlroots Wayland (Sway, Hyprland, etc.)
            self._capture_via_maim,        # X11 fallback
        ]
        for method in methods:
            if method():
                self._open_canvas()
                return

        self._notify_error(
            "Не удалось сделать скриншот ни одним из доступных методов.\n\n"
            "Wayland (GNOME/KDE): должен работать без установки утилит.\n"
            "Wayland (Sway/Hyprland): установите grim → sudo apt install grim\n"
            "X11: установите maim → sudo apt install maim"
        )

    # ------------------------------------------------------------------
    # Capture method 1: Qt native grabWindow
    # Works on X11 and some Wayland compositors.
    # On security-restricted Wayland it returns a black image — detected below.
    # ------------------------------------------------------------------

    def _capture_via_qt(self) -> bool:
        screen = QApplication.primaryScreen()
        if screen is None:
            return False
        pixmap = screen.grabWindow(0)
        if pixmap.isNull() or self._is_black_pixmap(pixmap):
            return False
        pixmap.save(SCREENSHOT_PATH, "PNG")
        return True

    def _is_black_pixmap(self, pixmap: QPixmap) -> bool:
        """Return True if all sampled pixels are (near-)black.

        Wayland compositors block grabWindow by returning a solid-black image
        instead of raising an error, so we have to detect it ourselves.
        """
        image = pixmap.toImage()
        w, h = image.width(), image.height()
        if w == 0 or h == 0:
            return True
        for row_f, col_f in _SAMPLE_GRID:
            pixel = image.pixel(int(w * col_f), int(h * row_f))
            r = (pixel >> 16) & 0xFF
            g = (pixel >> 8) & 0xFF
            b = pixel & 0xFF
            if r > _BLACK_THRESHOLD or g > _BLACK_THRESHOLD or b > _BLACK_THRESHOLD:
                return False
        return True

    # ------------------------------------------------------------------
    # Capture method 2: GNOME Shell DBus
    # Works on GNOME Wayland (Ubuntu, Fedora, Debian GNOME…).
    # Requires gdbus (part of glib2, installed by default on GNOME systems).
    # ------------------------------------------------------------------

    def _capture_via_dbus_gnome(self) -> bool:
        gdbus = shutil.which("gdbus")
        if not gdbus:
            return False
        cmd = [
            gdbus, "call", "--session",
            "--dest",        "org.gnome.Shell.Screenshot",
            "--object-path", "/org/gnome/Shell/Screenshot",
            "--method",      "org.gnome.Shell.Screenshot.Screenshot",
            "true",           # include cursor
            "false",          # no flash animation
            SCREENSHOT_PATH,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=15)
        except (subprocess.TimeoutExpired, OSError):
            return False
        # gdbus prints "(true, '/tmp/...')" on success
        if result.returncode != 0:
            return False
        out = result.stdout.decode(errors="replace").strip()
        return out.startswith("(true,") and os.path.exists(SCREENSHOT_PATH)

    # ------------------------------------------------------------------
    # Capture method 3: grim
    # Works on wlroots-based Wayland compositors (Sway, Hyprland, River…).
    # ------------------------------------------------------------------

    def _capture_via_grim(self) -> bool:
        grim = shutil.which("grim")
        if not grim:
            return False
        try:
            result = subprocess.run([grim, SCREENSHOT_PATH], capture_output=True, timeout=10)
            return result.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return False

    # ------------------------------------------------------------------
    # Capture method 4: maim
    # X11 fallback (also handles edge cases where Qt grabWindow failed on X11).
    # ------------------------------------------------------------------

    def _capture_via_maim(self) -> bool:
        maim = shutil.which("maim")
        if not maim:
            return False
        try:
            result = subprocess.run([maim, SCREENSHOT_PATH], capture_output=True, timeout=10)
            return result.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return False

    def _open_canvas(self) -> None:
        if self._canvas is not None:
            self._canvas.close()

        self._canvas = AnnotationCanvas(SCREENSHOT_PATH)
        self._canvas.show()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _notify_error(self, message: str) -> None:
        self.showMessage(
            "WaySnap — ошибка",
            message,
            QSystemTrayIcon.MessageIcon.Critical,
            5000,
        )
