import os
import shutil
import subprocess

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .canvas import AnnotationCanvas

SCREENSHOT_PATH = "/tmp/waysnap_shot.png"
CAPTURE_DELAY_MS = 300  # ms to wait after hiding menu so it disappears from screen


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

    def _detect_backend(self) -> str:
        """Return 'wayland' or 'x11' by inspecting environment variables."""
        if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
            return "wayland"
        if os.environ.get("WAYLAND_DISPLAY"):
            return "wayland"
        return "x11"

    def _find_capture_tool(self, backend: str) -> str | None:
        """Return full path to grim (Wayland) or maim (X11), or None if missing."""
        tool = "grim" if backend == "wayland" else "maim"
        return shutil.which(tool)

    def _capture_screen(self) -> None:
        backend = self._detect_backend()
        tool_path = self._find_capture_tool(backend)

        if tool_path is None:
            tool_name = "grim" if backend == "wayland" else "maim"
            self._notify_error(
                f"Утилита '{tool_name}' не найдена.\n"
                f"Установите: sudo apt install {tool_name}"
            )
            return

        cmd = [tool_path, SCREENSHOT_PATH]

        try:
            result = subprocess.run(cmd, capture_output=True, timeout=10)
        except subprocess.TimeoutExpired:
            self._notify_error("Захват экрана завис (timeout > 10 с)")
            return
        except OSError as exc:
            self._notify_error(f"Не удалось запустить захват: {exc}")
            return

        if result.returncode != 0:
            stderr = result.stderr.decode(errors="replace").strip()
            self._notify_error(f"Ошибка захвата (код {result.returncode}):\n{stderr}")
            return

        self._open_canvas()

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
