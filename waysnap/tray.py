import os
import shutil
import subprocess
import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .canvas import AnnotationCanvas

SCREENSHOT_PATH = "/tmp/waysnap_shot.png"
CAPTURE_DELAY_MS = 300  # ms to wait after hiding menu so it disappears from screen

# Minimum file size that counts as a real screenshot (any valid PNG >> this).
# Guards against opening a canvas over an empty or truncated file.
_FILE_MIN_BYTES = 4096
# How long to poll for the file after the DBus call (seconds).
_FILE_POLL_INTERVAL = 0.1
_FILE_POLL_TIMEOUT = 2.0


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
            self._capture_via_dbus_gnome,  # GNOME Wayland — primary on modern Ubuntu/Fedora
            self._capture_via_grim,        # wlroots Wayland (Sway, Hyprland, River…)
            self._capture_via_maim,        # X11 fallback
        ]
        for method in methods:
            if method():
                self._open_canvas()
                return

        self._notify_error(
            "Не удалось сделать скриншот ни одним из доступных методов.\n\n"
            "Wayland (GNOME): gdbus должен быть установлен по умолчанию.\n"
            "Wayland (Sway/Hyprland): sudo apt install grim\n"
            "X11: sudo apt install maim"
        )

    # ------------------------------------------------------------------
    # Capture method 1: GNOME Shell DBus
    # Primary method on GNOME Wayland (Ubuntu, Fedora, Debian GNOME…).
    # gdbus is part of glib2 and present by default on all GNOME systems.
    # ------------------------------------------------------------------

    def _capture_via_dbus_gnome(self) -> bool:
        gdbus = shutil.which("gdbus")
        if not gdbus:
            return False

        # Remove stale file from a previous run so the size-check below is reliable.
        try:
            os.remove(SCREENSHOT_PATH)
        except FileNotFoundError:
            pass

        cmd = [
            gdbus, "call", "--session",
            "--dest",        "org.gnome.Shell.Screenshot",
            "--object-path", "/org/gnome/Shell/Screenshot",
            "--method",      "org.gnome.Shell.Screenshot.Screenshot",
            "true",   # include cursor
            "false",  # no flash animation
            SCREENSHOT_PATH,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=15)
        except (subprocess.TimeoutExpired, OSError):
            return False

        if result.returncode != 0:
            return False

        # gdbus prints "(true, '/tmp/...')\n" on success
        out = result.stdout.decode(errors="replace").strip()
        if not out.startswith("(true,"):
            return False

        # The DBus response can arrive before the compositor finishes writing the
        # PNG to disk. Poll until the file reaches a sane size or we time out.
        deadline = time.monotonic() + _FILE_POLL_TIMEOUT
        while time.monotonic() < deadline:
            try:
                if os.path.getsize(SCREENSHOT_PATH) >= _FILE_MIN_BYTES:
                    return True
            except OSError:
                pass
            time.sleep(_FILE_POLL_INTERVAL)

        return False

    # ------------------------------------------------------------------
    # Capture method 2: grim
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
    # Capture method 3: maim
    # X11 fallback.
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
