"""Interpreter - Offline screen translator for Japanese retro games.

This application captures text from a target window, performs OCR using
MeikiOCR, translates using Sugoi V4, and displays subtitles in a
transparent overlay.
"""

__version__ = "0.1.0"
__commit__ = "cf21d0e"  # Short commit hash, updated on release

# Public API
from .__main__ import main, list_windows

__all__ = ["main", "list_windows", "__version__", "__commit__"]
