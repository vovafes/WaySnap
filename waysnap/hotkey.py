import logging

from PyQt6.QtCore import QObject, pyqtSignal

log = logging.getLogger(__name__)

# Default hotkey in pynput notation.
# On GNOME Wayland, make sure GNOME's own screenshot shortcuts don't conflict:
#   Settings → Keyboard → Keyboard Shortcuts → Screenshots → disable "Take a screenshot"
DEFAULT_HOTKEY = "<ctrl>+<print_screen>"


class HotkeyManager(QObject):
    """
    Listens for a global hotkey in a background thread via pynput.

    Works on X11 natively and on Wayland via XWayland (present on all
    Ubuntu/Fedora GNOME installs).  The listener thread is a daemon thread
    so it is cleaned up automatically when the process exits; call stop()
    for an explicit graceful shutdown.

    If pynput is not installed or the hotkey cannot be registered the class
    degrades silently — the rest of the app keeps working without a hotkey.
    """

    triggered = pyqtSignal()   # emitted on the Qt main thread (thread-safe)

    def __init__(self, hotkey: str = DEFAULT_HOTKEY) -> None:
        super().__init__()
        self._hotkey   = hotkey
        self._listener = None
        self._start()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _start(self) -> None:
        try:
            from pynput import keyboard  # noqa: PLC0415
            self._listener = keyboard.GlobalHotKeys({self._hotkey: self._fire})
            self._listener.daemon = True
            self._listener.start()
            log.info("Hotkey registered: %s", self._hotkey)
        except ImportError:
            log.warning(
                "pynput not found — global hotkey disabled. "
                "Install with: pip install pynput"
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not register hotkey %r: %s", self._hotkey, exc)

    def _fire(self) -> None:
        # Runs on pynput's thread; emit() marshals the call to the Qt main thread.
        log.debug("Hotkey fired: %s", self._hotkey)
        self.triggered.emit()

    # ── Public ────────────────────────────────────────────────────────────────

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
                log.info("Hotkey listener stopped")
            except Exception as exc:  # noqa: BLE001
                log.debug("Error stopping hotkey listener: %s", exc)
