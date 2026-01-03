"""PySide6 application entry point."""

import os
import platform
import sys

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from .. import log
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
    """Main application."""

    def __init__(self, config: Config):
        self._config = config
        self._app: QApplication = None
        self._window: MainWindow = None
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

        # Create main window
        self._window = MainWindow(self._config)

        # Handle app quit
        self._app.aboutToQuit.connect(self._on_quit)

    def _on_quit(self):
        """Handle application quit."""
        # Save config
        self._config.save()

        # Clean up window resources
        if self._window:
            self._window.cleanup()

        # Re-enable App Nap
        _enable_app_nap(self._app_nap_activity)

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

    # Configure logging (set INTERPRETER_DEBUG=1 for debug output)
    debug = os.environ.get("INTERPRETER_DEBUG", "").lower() in ("1", "true", "yes")
    log.configure(level="DEBUG" if debug else "INFO")

    # Suppress harmless warnings
    os.environ["PYTHONWARNINGS"] = "ignore::UserWarning:multiprocessing.resource_tracker"
    os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"

    # Load config
    config = Config.load()

    # Create and run app
    app = InterpreterApp(config)
    app.setup()
    sys.exit(app.run())
