import logging
import os
import shutil
import subprocess
import time

from PyQt6.QtCore import QCoreApplication, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .canvas import AnnotationCanvas

log = logging.getLogger(__name__)

SCREENSHOT_PATH = "/tmp/waysnap_shot.png"

# ── Timing constants ──────────────────────────────────────────────────────────
CAPTURE_DELAY_MS = 300   # ms: QTimer delay after hiding menu (gives WM time to redraw)
_PRE_CAPTURE_SLEEP = 0.4 # s:  extra sleep inside _capture_screen (compositor settle)

# ── File validation ───────────────────────────────────────────────────────────
_FILE_MIN_BYTES   = 4096  # a real screenshot PNG is always >> this
_FILE_POLL_S      = 0.1   # poll interval while waiting for file to appear
_FILE_POLL_MAX_S  = 3.0   # give up after this many seconds

# ── Black-image detection ─────────────────────────────────────────────────────
# maim via XWayland on GNOME Wayland captures the X11 root window which is
# black (GNOME Shell and all modern apps are Wayland-native, invisible to X11).
# We sample a 4×4 grid; if every point is near-black, the capture is useless.
_BLACK_SAMPLE_GRID = [(r, c) for r in (0.2, 0.4, 0.6, 0.8) for c in (0.2, 0.4, 0.6, 0.8)]
_BLACK_CHANNEL_MAX = 15   # 0-255; any channel above this means real content


class TrayIconManager(QSystemTrayIcon):
    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self._app = app
        self._canvas: AnnotationCanvas | None = None

        self.setIcon(self._make_placeholder_icon())
        self.setToolTip("WaySnap — нажмите для скриншота")
        self._build_menu()
        self.activated.connect(self._on_activated)

    # ── Icon ──────────────────────────────────────────────────────────────────

    def _make_placeholder_icon(self) -> QIcon:
        pixmap = QPixmap(32, 32)
        pixmap.fill(QColor("#2979FF"))
        p = QPainter(pixmap)
        p.setPen(QColor("white"))
        p.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        p.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "WS")
        p.end()
        return QIcon(pixmap)

    # ── Menu ──────────────────────────────────────────────────────────────────

    def _build_menu(self) -> None:
        menu = QMenu()
        menu.addAction("Сделать скриншот").triggered.connect(self._trigger_screenshot)
        menu.addSeparator()
        menu.addAction("Выход").triggered.connect(self._app.quit)
        self.setContextMenu(menu)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._trigger_screenshot()

    # ── Screenshot pipeline ───────────────────────────────────────────────────

    def _trigger_screenshot(self) -> None:
        # 1. Hide menu popup
        if menu := self.contextMenu():
            menu.hide()

        # 2. Hide canvas if it was open from a previous shot
        if self._canvas is not None:
            self._canvas.hide()

        # 3. Flush all pending Qt/WM events so the windows are gone from screen
        QCoreApplication.processEvents()

        # 4. Fire capture after a compositor-settle delay
        QTimer.singleShot(CAPTURE_DELAY_MS, self._capture_screen)

    def _capture_screen(self) -> None:
        # Extra sleep: gives the compositor time to finish redrawing after our
        # windows disappeared.  Without this, fast compositors sometimes still
        # include the WaySnap UI in the very first captured frame.
        log.info("Pre-capture sleep %.1f s …", _PRE_CAPTURE_SLEEP)
        time.sleep(_PRE_CAPTURE_SLEEP)

        desktop = self._detect_desktop()
        session = self._detect_session()
        log.info(
            "Environment: XDG_CURRENT_DESKTOP=%r  XDG_SESSION_TYPE=%r  "
            "→ desktop=%s  session=%s",
            os.environ.get("XDG_CURRENT_DESKTOP", "(unset)"),
            os.environ.get("XDG_SESSION_TYPE",    "(unset)"),
            desktop, session,
        )

        # Build an ordered capture chain for this desktop/session combo
        chain = self._build_capture_chain(desktop, session)
        log.info("Capture chain: %s", [m.__name__ for m in chain])

        # Remove stale file so the size-check cannot accidentally pass
        try:
            os.remove(SCREENSHOT_PATH)
            log.debug("Removed stale %s", SCREENSHOT_PATH)
        except FileNotFoundError:
            pass

        for method in chain:
            log.info("── Trying: %s", method.__name__)
            try:
                ok = method()
            except Exception as exc:
                log.error("   %s raised unexpectedly: %s", method.__name__, exc)
                ok = False

            if not ok:
                log.warning("   FAILED, trying next method …")
                continue

            # File exists and has size — but is it actually a real screenshot?
            if self._is_black_screenshot():
                log.warning(
                    "   %s produced a BLACK image — X11 root window is invisible "
                    "on Wayland. Treating as failure.", method.__name__
                )
                continue

            log.info("   SUCCESS via %s", method.__name__)
            self._open_canvas()
            return

        log.error("All capture methods exhausted. Screenshot not taken.")
        self._notify_error(
            "Не удалось сделать скриншот ни одним из доступных методов.\n\n"
            "Для GNOME Wayland (Ubuntu) установите gnome-screenshot:\n"
            "  sudo apt install gnome-screenshot\n\n"
            "Sway/Hyprland → sudo apt install grim\n"
            "Подробности: python main.py в терминале"
        )

    # ── Environment detection ─────────────────────────────────────────────────

    @staticmethod
    def _detect_desktop() -> str:
        raw = os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
        if "GNOME" in raw:
            return "gnome"
        if "KDE" in raw:
            return "kde"
        return "generic"

    @staticmethod
    def _detect_session() -> str:
        if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
            return "wayland"
        if os.environ.get("WAYLAND_DISPLAY"):
            return "wayland"
        return "x11"

    def _build_capture_chain(self, desktop: str, session: str) -> list:
        if desktop == "gnome":
            # GNOME never runs on wlroots, so grim is skipped entirely.
            # maim works reliably via XWayland (present on all Ubuntu/Fedora installs).
            # gnome-screenshot (sudo apt install gnome-screenshot) is the cleanest
            # native option when available.
            return [
                self._capture_gnome_screenshot,
                self._capture_gdbus_gnome,
                self._capture_maim,
            ]
        if desktop == "kde":
            # spectacle is the native KDE tool; grim covers KDE-on-wlroots edge cases.
            return [
                self._capture_spectacle,
                self._capture_grim,
                self._capture_maim,
            ]
        # Generic / unknown DE
        if session == "wayland":
            return [self._capture_grim, self._capture_gdbus_gnome, self._capture_maim]
        return [self._capture_maim, self._capture_grim]

    # ── Shared helpers ────────────────────────────────────────────────────────

    def _run(self, cmd: list[str], timeout: int = 15) -> "subprocess.CompletedProcess | None":
        """Run *cmd*, log stdout/stderr, return CompletedProcess on success or None."""
        log.debug("   $ %s", " ".join(cmd))
        binary = shutil.which(cmd[0])
        if binary is None:
            log.debug("   binary not found in PATH: %s", cmd[0])
            return None
        cmd = [binary] + cmd[1:]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            log.error("   command timed out (%d s): %s", timeout, cmd[0])
            return None
        except OSError as exc:
            log.error("   OSError: %s", exc)
            return None

        if result.stdout.strip():
            log.debug("   stdout: %s", result.stdout.decode(errors="replace").strip())
        if result.stderr.strip():
            log.warning("   stderr: %s", result.stderr.decode(errors="replace").strip())

        if result.returncode != 0:
            log.error("   exit code %d", result.returncode)
            return None
        return result

    def _wait_for_file(self) -> bool:
        """Poll until SCREENSHOT_PATH exists and is ≥ _FILE_MIN_BYTES, or time out."""
        deadline = time.monotonic() + _FILE_POLL_MAX_S
        while time.monotonic() < deadline:
            try:
                size = os.path.getsize(SCREENSHOT_PATH)
                if size >= _FILE_MIN_BYTES:
                    log.debug("   file ready: %d bytes", size)
                    return True
                log.debug("   file exists but too small (%d bytes), waiting …", size)
            except OSError:
                pass
            time.sleep(_FILE_POLL_S)

        try:
            final = os.path.getsize(SCREENSHOT_PATH)
        except OSError:
            final = 0
        log.error(
            "   file did not reach %d bytes within %.1f s (final size: %d bytes)",
            _FILE_MIN_BYTES, _FILE_POLL_MAX_S, final,
        )
        return False

    def _is_black_screenshot(self) -> bool:
        """Return True if every sampled pixel in SCREENSHOT_PATH is near-black.

        maim on GNOME Wayland captures the X11 root window via XWayland; that
        window has no Wayland content and is a solid or near-solid black surface.
        A file can be non-zero in size yet contain only a black image.
        """
        px = QPixmap(SCREENSHOT_PATH)
        if px.isNull():
            log.error("   _is_black_screenshot: QPixmap failed to load file")
            return True

        img = px.toImage()
        w, h = img.width(), img.height()
        log.debug("   image dimensions: %d×%d", w, h)

        for row_f, col_f in _BLACK_SAMPLE_GRID:
            pixel = img.pixel(int(w * col_f), int(h * row_f))
            r = (pixel >> 16) & 0xFF
            g = (pixel >> 8)  & 0xFF
            b =  pixel        & 0xFF
            if r > _BLACK_CHANNEL_MAX or g > _BLACK_CHANNEL_MAX or b > _BLACK_CHANNEL_MAX:
                log.debug("   non-black pixel found at (%.0f%%,%.0f%%): rgb(%d,%d,%d)",
                          col_f * 100, row_f * 100, r, g, b)
                return False

        log.warning("   all 16 sample points are near-black → image is black")
        return True

    # ── Capture methods ───────────────────────────────────────────────────────

    def _capture_gnome_screenshot(self) -> bool:
        """gnome-screenshot — GNOME Wayland primary (Ubuntu, Fedora, Debian)."""
        result = self._run(["gnome-screenshot", "-f", SCREENSHOT_PATH])
        if result is None:
            return False
        return self._wait_for_file()

    def _capture_gdbus_gnome(self) -> bool:
        """GNOME Shell DBus — fallback when gnome-screenshot is absent."""
        result = self._run([
            "gdbus", "call", "--session",
            "--dest",        "org.gnome.Shell.Screenshot",
            "--object-path", "/org/gnome/Shell/Screenshot",
            "--method",      "org.gnome.Shell.Screenshot.Screenshot",
            "true",   # include cursor
            "false",  # no flash animation
            SCREENSHOT_PATH,
        ])
        if result is None:
            return False
        out = result.stdout.decode(errors="replace").strip()
        if not out.startswith("(true,"):
            log.error("   gdbus returned unexpected output: %r", out)
            return False
        return self._wait_for_file()

    def _capture_spectacle(self) -> bool:
        """KDE Spectacle — background mode, no GUI, write to file."""
        result = self._run(["spectacle", "-b", "-n", "-o", SCREENSHOT_PATH])
        if result is None:
            return False
        return self._wait_for_file()

    def _capture_grim(self) -> bool:
        """grim — wlroots Wayland (Sway, Hyprland, River …)."""
        result = self._run(["grim", SCREENSHOT_PATH])
        if result is None:
            return False
        return self._wait_for_file()

    def _capture_maim(self) -> bool:
        """maim — X11."""
        result = self._run(["maim", SCREENSHOT_PATH])
        if result is None:
            return False
        return self._wait_for_file()

    # ── Canvas ────────────────────────────────────────────────────────────────

    def _open_canvas(self) -> None:
        if self._canvas is not None:
            self._canvas.close()
        self._canvas = AnnotationCanvas(SCREENSHOT_PATH)
        self._canvas.show()

    # ── Notification ──────────────────────────────────────────────────────────

    def _notify_error(self, message: str) -> None:
        self.showMessage(
            "WaySnap — ошибка",
            message,
            QSystemTrayIcon.MessageIcon.Critical,
            6000,
        )
