import logging
import os
import shutil
import subprocess
import sys
import time

from PyQt6.QtCore import QCoreApplication, QRect, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .canvas import AnnotationCanvas

log = logging.getLogger(__name__)

SCREENSHOT_PATH = "/tmp/waysnap_shot.png"
_PORTAL_HELPER  = os.path.join(os.path.dirname(__file__), "portal_helper.py")
REGION_PATH     = "/tmp/waysnap_region.png"

# ── Timing ────────────────────────────────────────────────────────────────────
_MENU_HIDE_DELAY_MS   = 200   # ms: wait after hiding menu before opening overlay
_POST_SELECT_DELAY_MS = 300   # ms: wait after overlay closes before capturing
                               # (gives compositor time to redraw the desktop)

# ── File validation ───────────────────────────────────────────────────────────
_FILE_MIN_BYTES  = 4096
_FILE_POLL_S     = 0.1
_FILE_POLL_MAX_S = 3.0

# ── Black-image detection ─────────────────────────────────────────────────────
# maim on GNOME Wayland captures the X11 root window (black) via XWayland.
_BLACK_GRID      = [(r, c) for r in (0.2, 0.4, 0.6, 0.8) for c in (0.2, 0.4, 0.6, 0.8)]
_BLACK_THRESHOLD = 15   # channel value; below this → considered black


class TrayIconManager(QSystemTrayIcon):
    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self._app    = app
        self._canvas: AnnotationCanvas | None = None

        self.setIcon(self._make_placeholder_icon())
        self.setToolTip("WaySnap")
        self._build_menu()
        self.activated.connect(self._on_activated)

    # ── Icon ──────────────────────────────────────────────────────────────────

    def _make_placeholder_icon(self) -> QIcon:
        px = QPixmap(32, 32)
        px.fill(QColor("#2979FF"))
        p = QPainter(px)
        p.setPen(QColor("white"))
        p.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        p.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, "WS")
        p.end()
        return QIcon(px)

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

    # ── Step 1: open selection overlay ───────────────────────────────────────
    #   No screenshot is taken here.  The user sees the LIVE desktop through
    #   the transparent overlay and draws a selection rectangle.

    def _trigger_screenshot(self) -> None:
        if menu := self.contextMenu():
            menu.hide()
        if self._canvas is not None:
            self._canvas.close()
        QCoreApplication.processEvents()
        QTimer.singleShot(_MENU_HIDE_DELAY_MS, self._open_canvas)

    def _open_canvas(self) -> None:
        if self._canvas is not None:
            self._canvas.close()
        self._canvas = AnnotationCanvas()
        self._canvas.region_confirmed.connect(self._on_region_confirmed)
        self._canvas.show()

    # ── Step 2: region confirmed — wait, then capture ────────────────────────

    def _on_region_confirmed(self, sel: QRect) -> None:
        """Canvas closed, start a short pause so the compositor redraws the desktop."""
        log.info("Selection: %s — waiting %d ms before capture", sel, _POST_SELECT_DELAY_MS)
        QTimer.singleShot(_POST_SELECT_DELAY_MS, lambda: self._capture_region(sel))

    # ── Step 3: capture the full screen, then crop ───────────────────────────

    def _capture_region(self, sel: QRect) -> None:
        desktop = self._detect_desktop()
        session = self._detect_session()
        log.info(
            "Capture for region %s  (desktop=%s, session=%s)",
            sel, desktop, session,
        )

        chain = self._build_capture_chain(desktop, session)
        log.info("Capture chain: %s", [m.__name__ for m in chain])

        try:
            os.remove(SCREENSHOT_PATH)
        except FileNotFoundError:
            pass

        for method in chain:
            log.info("── Trying: %s", method.__name__)
            try:
                ok = method()
            except Exception as exc:
                log.error("   raised: %s", exc)
                ok = False

            if not ok:
                log.warning("   FAILED, trying next …")
                continue

            if self._is_black_screenshot():
                log.warning("   BLACK image — trying next …")
                continue

            log.info("   SUCCESS via %s", method.__name__)
            self._crop_and_save(sel)
            return

        log.error("All capture methods exhausted.")
        self._notify_error(
            "Не удалось сделать скриншот ни одним из методов.\n\n"
            "GNOME Wayland (Ubuntu/Fedora):\n"
            "  sudo apt install gnome-screenshot\n\n"
            "Sway / Hyprland:\n"
            "  sudo apt install grim\n\n"
            "Подробности: python main.py в терминале"
        )

    def _crop_and_save(self, sel: QRect) -> None:
        """Load the full screenshot, crop to *sel* (screen/widget coords), save."""
        px = QPixmap(SCREENSHOT_PATH)
        if px.isNull():
            log.error("Cannot load %s", SCREENSHOT_PATH)
            return

        # sel is in logical screen pixels (widget geometry == screen geometry).
        # The captured image may have a different pixel density (HiDPI).
        screen = QApplication.primaryScreen()
        if screen:
            geom = screen.geometry()
            sx = px.width()  / geom.width()
            sy = px.height() / geom.height()
        else:
            sx = sy = 1.0

        src = QRect(
            int(sel.x() * sx), int(sel.y() * sy),
            max(1, int(sel.width()  * sx)),
            max(1, int(sel.height() * sy)),
        )
        log.info("Crop: widget %s → pixmap %s", sel, src)

        cropped = px.copy(src)
        cropped.save(REGION_PATH, "PNG")
        QApplication.clipboard().setPixmap(cropped)

        log.info("Saved %d×%d px → %s  (clipboard)", src.width(), src.height(), REGION_PATH)
        self.showMessage(
            "WaySnap",
            f"Скопировано в буфер  {src.width()} × {src.height()} px",
            QSystemTrayIcon.MessageIcon.Information,
            3000,
        )

    # ── Environment detection ─────────────────────────────────────────────────

    @staticmethod
    def _detect_desktop() -> str:
        raw = os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
        if "GNOME" in raw: return "gnome"
        if "KDE"   in raw: return "kde"
        return "generic"

    @staticmethod
    def _detect_session() -> str:
        if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland": return "wayland"
        if os.environ.get("WAYLAND_DISPLAY"):                            return "wayland"
        return "x11"

    def _build_capture_chain(self, desktop: str, session: str) -> list:
        # XDG portal is first everywhere on Wayland: it works on GNOME 42+,
        # KDE Plasma 5.25+, and any compositor that ships xdg-desktop-portal.
        if desktop == "gnome":
            return [self._capture_via_portal,
                    self._capture_gnome_screenshot,
                    self._capture_gdbus_gnome,
                    self._capture_maim]
        if desktop == "kde":
            return [self._capture_via_portal,
                    self._capture_spectacle,
                    self._capture_grim,
                    self._capture_maim]
        if session == "wayland":
            return [self._capture_via_portal,
                    self._capture_grim,
                    self._capture_gdbus_gnome,
                    self._capture_maim]
        return [self._capture_maim, self._capture_grim]

    # ── Shared helpers ────────────────────────────────────────────────────────

    def _run(self, cmd: list[str], timeout: int = 15) -> "subprocess.CompletedProcess | None":
        log.debug("   $ %s", " ".join(cmd))
        binary = shutil.which(cmd[0])
        if binary is None:
            log.debug("   not found in PATH: %s", cmd[0])
            return None
        try:
            result = subprocess.run([binary] + cmd[1:], capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            log.error("   timeout (%ds)", timeout)
            return None
        except OSError as exc:
            log.error("   OSError: %s", exc)
            return None

        if result.stdout.strip():
            log.debug("   stdout: %s", result.stdout.decode(errors="replace").strip())
        if result.stderr.strip():
            log.warning("   stderr: %s", result.stderr.decode(errors="replace").strip())
        if result.returncode != 0:
            log.error("   exit %d", result.returncode)
            return None
        return result

    def _wait_for_file(self) -> bool:
        deadline = time.monotonic() + _FILE_POLL_MAX_S
        while time.monotonic() < deadline:
            try:
                size = os.path.getsize(SCREENSHOT_PATH)
                if size >= _FILE_MIN_BYTES:
                    log.debug("   file ready: %d bytes", size)
                    return True
                log.debug("   too small (%d B), waiting …", size)
            except OSError:
                pass
            time.sleep(_FILE_POLL_S)
        log.error("   file never reached %d B within %.1fs", _FILE_MIN_BYTES, _FILE_POLL_MAX_S)
        return False

    def _is_black_screenshot(self) -> bool:
        px = QPixmap(SCREENSHOT_PATH)
        if px.isNull():
            return True
        img = px.toImage()
        w, h = img.width(), img.height()
        for row_f, col_f in _BLACK_GRID:
            pix = img.pixel(int(w * col_f), int(h * row_f))
            if ((pix >> 16) & 0xFF) > _BLACK_THRESHOLD: return False
            if ((pix >>  8) & 0xFF) > _BLACK_THRESHOLD: return False
            if  (pix        & 0xFF) > _BLACK_THRESHOLD: return False
        log.warning("   all sample points are black → image is empty")
        return True

    # ── Capture methods ───────────────────────────────────────────────────────

    def _capture_via_portal(self) -> bool:
        """XDG Desktop Portal — universal Wayland method (GNOME 42+, KDE 5.25+).

        Runs portal_helper.py as a subprocess so GLib's event loop doesn't
        conflict with Qt's.  Requires python3-gi (pre-installed on Ubuntu GNOME
        and Fedora; install on others: sudo apt install python3-gi).
        """
        if not os.path.isfile(_PORTAL_HELPER):
            log.error("portal_helper.py not found: %s", _PORTAL_HELPER)
            return False
        r = self._run([sys.executable, _PORTAL_HELPER, SCREENSHOT_PATH], timeout=20)
        return r is not None and self._wait_for_file()

    def _capture_gnome_screenshot(self) -> bool:
        """gnome-screenshot (sudo apt install gnome-screenshot) — GNOME Wayland."""
        r = self._run(["gnome-screenshot", "-f", SCREENSHOT_PATH])
        return r is not None and self._wait_for_file()

    def _capture_gdbus_gnome(self) -> bool:
        """GNOME Shell DBus — fallback when gnome-screenshot is absent."""
        r = self._run([
            "gdbus", "call", "--session",
            "--dest",        "org.gnome.Shell.Screenshot",
            "--object-path", "/org/gnome/Shell/Screenshot",
            "--method",      "org.gnome.Shell.Screenshot.Screenshot",
            "true", "false", SCREENSHOT_PATH,
        ])
        if r is None:
            return False
        if not r.stdout.decode(errors="replace").strip().startswith("(true,"):
            return False
        return self._wait_for_file()

    def _capture_spectacle(self) -> bool:
        """KDE Spectacle."""
        r = self._run(["spectacle", "-b", "-n", "-o", SCREENSHOT_PATH])
        return r is not None and self._wait_for_file()

    def _capture_grim(self) -> bool:
        """grim — wlroots Wayland (Sway, Hyprland …)."""
        r = self._run(["grim", SCREENSHOT_PATH])
        return r is not None and self._wait_for_file()

    def _capture_maim(self) -> bool:
        """maim — X11 / XWayland fallback."""
        r = self._run(["maim", SCREENSHOT_PATH])
        return r is not None and self._wait_for_file()

    # ── Canvas / notification ─────────────────────────────────────────────────

    def _notify_error(self, message: str) -> None:
        self.showMessage("WaySnap — ошибка", message,
                         QSystemTrayIcon.MessageIcon.Critical, 7000)
