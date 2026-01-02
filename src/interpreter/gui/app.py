"""PySide6 application entry point with system tray."""

import platform
import sys

from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap, QAction

from ..config import Config
from .main_window import MainWindow


def _disable_app_nap():
    """Disable macOS App Nap to prevent throttling when on different Space.

    When the target window is fullscreen (on a different Space), macOS may
    throttle our app thinking it's not visible. This prevents that.
    """
    if platform.system() != "Darwin":
        return None

    try:
        from Foundation import NSProcessInfo

        process_info = NSProcessInfo.processInfo()
        # NSActivityUserInitiatedAllowingIdleSystemSleep = 0x00FFFFFF
        # This tells macOS we're doing important user-initiated work
        activity = process_info.beginActivityWithOptions_reason_(
            0x00FFFFFF,
            "Real-time screen capture and translation"
        )
        return activity
    except ImportError:
        return None
    except Exception:
        return None


def _enable_app_nap(activity):
    """Re-enable App Nap by ending the activity."""
    if activity is None:
        return

    try:
        from Foundation import NSProcessInfo
        process_info = NSProcessInfo.processInfo()
        process_info.endActivity_(activity)
    except Exception:
        pass


class InterpreterApp:
    """Main application with system tray integration."""

    def __init__(self, config: Config):
        self._config = config
        self._app: QApplication = None
        self._window: MainWindow = None
        self._tray: QSystemTrayIcon = None
        self._app_nap_activity = None

    def setup(self):
        """Set up the application."""
        # Disable App Nap to prevent throttling when capturing fullscreen windows
        self._app_nap_activity = _disable_app_nap()

        # Enable high DPI scaling
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )

        self._app = QApplication(sys.argv)
        self._app.setApplicationName("Interpreter")
        self._app.setQuitOnLastWindowClosed(False)  # Keep running in tray

        # Create main window
        self._window = MainWindow(self._config)

        # Set up system tray
        self._setup_tray()

        # Handle app quit
        self._app.aboutToQuit.connect(self._on_quit)

    def _setup_tray(self):
        """Set up system tray icon and menu."""
        self._tray = QSystemTrayIcon(self._window)

        # Create a simple icon (colored square)
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.darkCyan)
        self._tray.setIcon(QIcon(pixmap))
        self._tray.setToolTip("Interpreter")

        # Tray menu
        menu = QMenu()

        show_action = QAction("Show", self._window)
        show_action.triggered.connect(self._show_window)
        menu.addAction(show_action)

        hide_action = QAction("Hide", self._window)
        hide_action.triggered.connect(self._window.hide)
        menu.addAction(hide_action)

        menu.addSeparator()

        quit_action = QAction("Quit", self._window)
        quit_action.triggered.connect(self._quit)
        menu.addAction(quit_action)

        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _show_window(self):
        """Show and raise the main window."""
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()

    def _on_tray_activated(self, reason):
        """Handle tray icon activation."""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self._window.isVisible():
                self._window.hide()
            else:
                self._show_window()

    def _on_quit(self):
        """Handle application quit."""
        # Save config
        self._config.save()

        # Clean up window resources
        if self._window:
            self._window.cleanup()

        # Re-enable App Nap
        _enable_app_nap(self._app_nap_activity)

    def _quit(self):
        """Quit the application."""
        self._app.quit()

    def run(self) -> int:
        """Run the application.

        Returns:
            Exit code.
        """
        self._window.show()
        return self._app.exec()


def run():
    """Main entry point for GUI application."""
    # Setup GPU libraries early (before any CUDA-dependent imports)
    from ..gpu import setup as setup_gpu
    setup_gpu()

    # Suppress harmless warnings
    import os
    os.environ["PYTHONWARNINGS"] = "ignore::UserWarning:multiprocessing.resource_tracker"
    os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"

    # Load config
    config = Config.load()

    # Create and run app
    app = InterpreterApp(config)
    app.setup()
    sys.exit(app.run())
