"""PySide6 application entry point."""

import argparse
import os
import platform
import sys
from pathlib import Path

# On Linux, force Qt to use X11/XWayland instead of native Wayland.
# This gives us proper stay-on-top behavior for overlay windows.
# Native Wayland compositors (especially GNOME) don't respect WindowStaysOnTopHint.
# Must be set BEFORE importing Qt.
if platform.system() == "Linux" and "QT_QPA_PLATFORM" not in os.environ:
    os.environ["QT_QPA_PLATFORM"] = "xcb"

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .. import __version__, log
from ..config import Config
from .main_window import MainWindow


def _get_gpu_info() -> str:
    """Get GPU/CUDA info string for logging."""
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() > 0:
            # Try to get CUDA version from environment (set by nvidia libs)
            cuda_version = os.environ.get("CUDA_VERSION", "")
            if cuda_version:
                return f"cuda {cuda_version}"
            # Try cudart version from ctranslate2
            try:
                cuda_ver = ctranslate2.get_cuda_runtime_version()
                if cuda_ver:
                    major = cuda_ver // 1000
                    minor = (cuda_ver % 1000) // 10
                    return f"cuda {major}.{minor}"
            except (AttributeError, Exception):
                pass
            return "cuda"
        return "cpu"
    except Exception:
        return "cpu"


class InterpreterApp:
    """Main application."""

    def __init__(self, config: Config):
        self._config = config
        self._app: QApplication | None = None
        self._window: MainWindow | None = None

    def setup(self):
        """Set up the application."""
        # Enable high DPI scaling
        QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

        # Set desktop filename before creating QApplication (required for Wayland app_id)
        if platform.system() == "Linux":
            QApplication.setDesktopFileName("interpreter-v2")

        self._app = QApplication(sys.argv)
        self._app.setApplicationName("Interpreter")

        # Set application icon
        icon_path = self._get_icon_path()
        icon = None
        if icon_path.exists():
            icon = QIcon(str(icon_path))
            self._app.setWindowIcon(icon)

        # Create main window
        self._window = MainWindow(self._config)

        # Also set icon on main window (needed for Linux taskbar)
        if icon:
            self._window.setWindowIcon(icon)

        # Handle app quit
        self._app.aboutToQuit.connect(self._on_quit)

    def _get_icon_path(self) -> Path:
        """Get platform-appropriate icon path."""
        resources = Path(__file__).parent.parent / "resources" / "icons"
        system = platform.system()
        if system == "Darwin":
            return resources / "icon.icns"
        elif system == "Windows":
            return resources / "icon.ico"
        else:
            return resources / "icon.png"

    def _on_quit(self):
        """Handle application quit."""
        logger = log.get_logger()

        # Save banner position before saving config
        if self._window:
            pos = self._window.get_banner_position()
            logger.debug("saving banner position", x=pos[0], y=pos[1])
            self._config.banner_x, self._config.banner_y = pos

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

    # Configure pipewire-capture logging on Wayland (must be after log.configure)
    from ..capture import _is_wayland_session

    if _is_wayland_session:
        from ..capture.linux_wayland import configure_logging as configure_wayland_logging

        configure_wayland_logging(args.debug)

    logger = log.get_logger()
    logger.info(f"interpreter v{__version__}")

    # Get OS version string (human-readable on Windows)
    if platform.system() == "Windows":
        from ..capture.windows import get_windows_version_string

        os_version = get_windows_version_string()
    else:
        os_version = platform.version()

    logger.info(
        "system",
        platform=platform.system(),
        version=os_version,
        python=platform.python_version(),
        gpu=_get_gpu_info(),
    )

    # Suppress harmless warnings
    os.environ["PYTHONWARNINGS"] = "ignore::UserWarning:multiprocessing.resource_tracker"
    os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
    os.environ["HF_HUB_VERBOSITY"] = "error"  # Suppress unauthenticated request warnings

    # Load config
    config = Config.load()

    # Create and run app
    app = InterpreterApp(config)
    app.setup()
    sys.exit(app.run())
