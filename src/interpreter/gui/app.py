"""PySide6 application entry point."""

import argparse
import os
import sys

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from .. import log
from ..config import Config
from .main_window import MainWindow


class InterpreterApp:
    """Main application."""

    def __init__(self, config: Config):
        self._config = config
        self._app: QApplication = None
        self._window: MainWindow = None

    def setup(self):
        """Set up the application."""
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

    def run(self) -> int:
        """Run the application.

        Returns:
            Exit code.
        """
        self._window.show()
        return self._app.exec()


def run():
    """Main entry point for GUI application."""
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Interpreter - Screen translator for Japanese games")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    # Setup GPU libraries early (before any CUDA-dependent imports)
    from ..gpu import setup as setup_gpu
    setup_gpu()

    # Configure logging
    log.configure(level="DEBUG" if args.debug else "INFO")

    # Suppress harmless warnings
    os.environ["PYTHONWARNINGS"] = "ignore::UserWarning:multiprocessing.resource_tracker"
    os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"

    # Load config
    config = Config.load()

    # Create and run app
    app = InterpreterApp(config)
    app.setup()
    sys.exit(app.run())
