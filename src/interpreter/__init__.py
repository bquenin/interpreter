"""Interpreter - Offline screen translator for Japanese retro games.

This application captures text from a target window, performs OCR using
MeikiOCR, translates using Sugoi V4, and displays subtitles in a
transparent overlay.
"""

__version__ = "2.0.1"


def main():
    """Entry point for the application."""
    from .__main__ import main as _main
    return _main()


def list_windows():
    """List available windows."""
    from .__main__ import list_windows as _list_windows
    return _list_windows()


__all__ = ["main", "list_windows", "__version__"]
