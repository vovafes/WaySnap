import sys

from PyQt6.QtWidgets import QApplication, QSystemTrayIcon

from waysnap.tray import TrayIconManager


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("WaySnap")
    app.setQuitOnLastWindowClosed(False)  # keep alive when canvas is closed

    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("ERROR: system tray not available on this desktop environment", file=sys.stderr)
        sys.exit(1)

    tray = TrayIconManager(app)
    tray.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
