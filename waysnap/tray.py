import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QCoreApplication, QRect, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap, QScreen
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .canvas import AnnotationCanvas

log = logging.getLogger(__name__)

SCREENSHOT_PATH = "/tmp/waysnap_shot.png"
_PORTAL_HELPER  = os.path.join(os.path.dirname(__file__), "portal_helper.py")


def _save_dir() -> Path:
    """Return ~/Pictures/WaySnap (via xdg-user-dir), creating it if needed."""
    try:
        result = subprocess.run(
            ["xdg-user-dir", "PICTURES"], capture_output=True, text=True, timeout=3
        )
        base = Path(result.stdout.strip()) if result.returncode == 0 else Path.home() / "Pictures"
    except Exception:
        base = Path.home() / "Pictures"
    d = base / "WaySnap"
    d.mkdir(parents=True, exist_ok=True)
    return d

# ── Timing ────────────────────────────────────────────────────────────────────
# How long to wait (ms) after hiding the menu before capturing.
# Must be long enough for the menu to disappear from the compositor's frame.
_PRE_CAPTURE_DELAY_MS = 400

# ── File validation ───────────────────────────────────────────────────────────
_FILE_MIN_BYTES  = 4096
_FILE_POLL_S     = 0.1
_FILE_POLL_MAX_S = 5.0

# ── Black-image detection ─────────────────────────────────────────────────────
_BLACK_GRID      = [(r, c) for r in (0.2, 0.4, 0.6, 0.8) for c in (0.2, 0.4, 0.6, 0.8)]
_BLACK_THRESHOLD = 15


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
        # Rebuild screen list each time the menu is opened
        menu.aboutToShow.connect(lambda: self._populate_menu(menu))
        self._populate_menu(menu)
        self.setContextMenu(menu)

    def _populate_menu(self, menu: QMenu) -> None:
        menu.clear()
        screens = QApplication.screens()

        if len(screens) == 1:
            menu.addAction("Take screenshot").triggered.connect(
                lambda: self._trigger_screenshot()
            )
        else:
            menu.addAction("All screens").triggered.connect(
                lambda: self._trigger_screenshot()
            )
            for i, s in enumerate(screens):
                g     = s.geometry()
                label = f"Screen {i + 1}  ({g.width()}×{g.height()})"
                menu.addAction(label).triggered.connect(
                    lambda checked=False, scr=s: self._trigger_screenshot(scr)
                )

        menu.addSeparator()
        menu.addAction("Quit").triggered.connect(self._app.quit)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._trigger_screenshot()

    # ── Step 1: hide UI, wait, capture full screen ────────────────────────────

    def _trigger_screenshot(self, target_screen: QScreen | None = None) -> None:
        if menu := self.contextMenu():
            menu.hide()
        if self._canvas is not None:
            self._canvas.hide()
        QCoreApplication.processEvents()
        QTimer.singleShot(
            _PRE_CAPTURE_DELAY_MS,
            lambda: self._capture_full_screen(target_screen),
        )

    def _capture_full_screen(self, target_screen: QScreen | None = None) -> None:
        desktop = self._detect_desktop()
        session = self._detect_session()
        log.info("Capturing full screen (desktop=%s, session=%s)", desktop, session)

        chain = self._build_capture_chain(desktop, session)
        log.info("Chain: %s", [m.__name__ for m in chain])

        try:
            os.remove(SCREENSHOT_PATH)
        except FileNotFoundError:
            pass

        for method in chain:
            log.info("── %s", method.__name__)
            try:
                ok = method()
            except Exception as exc:
                log.error("   raised: %s", exc)
                ok = False

            if not ok:
                log.warning("   failed")
                continue

            if self._is_black_screenshot():
                log.warning("   black image — skipping")
                continue

            log.info("   SUCCESS")
            if target_screen is not None:
                self._crop_screenshot_to_screen(target_screen)
            self._open_canvas(target_screen)
            return

        log.error("All capture methods failed.")
        self._notify_error(
            "Could not capture the screen with any available method.\n\n"
            "GNOME Wayland:\n  sudo apt install gnome-screenshot\n\n"
            "Sway / Hyprland:\n  sudo apt install grim"
        )

    # ── Step 2: show frozen overlay, user picks region ────────────────────────

    def _crop_screenshot_to_screen(self, screen: QScreen) -> None:
        """Overwrite SCREENSHOT_PATH with only the pixels belonging to *screen*."""
        px = QPixmap(SCREENSHOT_PATH)
        if px.isNull():
            return

        # Virtual desktop bounding box (logical pixels, all screens combined)
        virtual = QRect()
        for s in QApplication.screens():
            virtual = virtual.united(s.geometry())

        # Scale from logical virtual-desktop coords to physical screenshot pixels
        sx = px.width()  / virtual.width()
        sy = px.height() / virtual.height()

        g    = screen.geometry()
        crop = QRect(
            int((g.x() - virtual.x()) * sx),
            int((g.y() - virtual.y()) * sy),
            max(1, int(g.width()  * sx)),
            max(1, int(g.height() * sy)),
        )
        log.info("Screen crop: logical %s → px %s", g, crop)
        px.copy(crop).save(SCREENSHOT_PATH, "PNG")

    def _open_canvas(self, target_screen: QScreen | None = None) -> None:
        if self._canvas is not None:
            self._canvas.close()
        self._canvas = AnnotationCanvas(SCREENSHOT_PATH, target_screen=target_screen)
        self._canvas.region_confirmed.connect(self._on_region_confirmed)
        self._canvas.show()

    # ── Step 3: crop and save the selected region ─────────────────────────────

    def _on_region_confirmed(self, sel: QRect) -> None:
        px = QPixmap(SCREENSHOT_PATH)
        if px.isNull():
            log.error("Cannot load %s for crop", SCREENSHOT_PATH)
            return

        # sel is in logical screen pixels; scale to physical pixmap pixels
        screen = QApplication.primaryScreen()
        if screen:
            g  = screen.geometry()
            sx = px.width()  / g.width()
            sy = px.height() / g.height()
        else:
            sx = sy = 1.0

        src = QRect(
            int(sel.x() * sx), int(sel.y() * sy),
            max(1, int(sel.width()  * sx)),
            max(1, int(sel.height() * sy)),
        )
        log.info("Crop: widget %s → px %s", sel, src)

        cropped = px.copy(src)

        # ── Permanent save ────────────────────────────────────────────────────
        filename  = datetime.now().strftime("waysnap_%Y-%m-%d_%H-%M-%S.png")
        save_path = _save_dir() / filename
        cropped.save(str(save_path), "PNG")
        log.info("Saved %d×%d → %s", src.width(), src.height(), save_path)

        # ── Clipboard ─────────────────────────────────────────────────────────
        QApplication.clipboard().setPixmap(cropped)
        log.info("Copied to clipboard")

        self.showMessage(
            "WaySnap",
            f"Saved  {src.width()} × {src.height()} px\n{save_path}",
            QSystemTrayIcon.MessageIcon.Information,
            4000,
        )

    # ── Environment ───────────────────────────────────────────────────────────

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
                    self._capture_maim]
        return [self._capture_maim, self._capture_grim]

    # ── Shared helpers ────────────────────────────────────────────────────────

    def _run(self, cmd: list[str], timeout: int = 15) -> "subprocess.CompletedProcess | None":
        log.debug("   $ %s", " ".join(cmd))
        binary = shutil.which(cmd[0])
        if not binary:
            log.debug("   not in PATH: %s", cmd[0])
            return None
        try:
            r = subprocess.run([binary] + cmd[1:], capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            log.error("   timeout (%ds)", timeout)
            return None
        except OSError as exc:
            log.error("   OSError: %s", exc)
            return None
        if r.stdout.strip():
            log.debug("   stdout: %s", r.stdout.decode(errors="replace").strip())
        if r.stderr.strip():
            log.warning("   stderr: %s", r.stderr.decode(errors="replace").strip())
        if r.returncode != 0:
            log.error("   exit %d", r.returncode)
            return None
        return r

    def _wait_for_file(self) -> bool:
        deadline = time.monotonic() + _FILE_POLL_MAX_S
        while time.monotonic() < deadline:
            try:
                if os.path.getsize(SCREENSHOT_PATH) >= _FILE_MIN_BYTES:
                    log.debug("   file ready: %d B", os.path.getsize(SCREENSHOT_PATH))
                    return True
            except OSError:
                pass
            time.sleep(_FILE_POLL_S)
        log.error("   file never reached %d B", _FILE_MIN_BYTES)
        return False

    def _is_black_screenshot(self) -> bool:
        px = QPixmap(SCREENSHOT_PATH)
        if px.isNull():
            return True
        img = px.toImage()
        w, h = img.width(), img.height()
        for rf, cf in _BLACK_GRID:
            pix = img.pixel(int(w * cf), int(h * rf))
            if ((pix >> 16) & 0xFF) > _BLACK_THRESHOLD: return False
            if ((pix >>  8) & 0xFF) > _BLACK_THRESHOLD: return False
            if  (pix        & 0xFF) > _BLACK_THRESHOLD: return False
        log.warning("   all sample points black")
        return True

    # ── Capture methods ───────────────────────────────────────────────────────

    def _capture_via_portal(self) -> bool:
        """XDG Desktop Portal — GNOME 42+, KDE 5.25+ (needs system python3-gi)."""
        if not os.path.isfile(_PORTAL_HELPER):
            return False
        r = self._run(["python3", _PORTAL_HELPER, SCREENSHOT_PATH], timeout=20)
        return r is not None and self._wait_for_file()

    def _capture_gnome_screenshot(self) -> bool:
        r = self._run(["gnome-screenshot", "-f", SCREENSHOT_PATH])
        return r is not None and self._wait_for_file()

    def _capture_gdbus_gnome(self) -> bool:
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
        r = self._run(["spectacle", "-b", "-n", "-o", SCREENSHOT_PATH])
        return r is not None and self._wait_for_file()

    def _capture_grim(self) -> bool:
        r = self._run(["grim", SCREENSHOT_PATH])
        return r is not None and self._wait_for_file()

    def _capture_maim(self) -> bool:
        r = self._run(["maim", SCREENSHOT_PATH])
        return r is not None and self._wait_for_file()

    # ── Notification ──────────────────────────────────────────────────────────

    def _notify_error(self, message: str) -> None:
        self.showMessage("WaySnap — error", message,
                         QSystemTrayIcon.MessageIcon.Critical, 7000)
