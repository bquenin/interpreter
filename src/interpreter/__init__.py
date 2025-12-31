"""Interpreter - Offline screen translator for Japanese retro games.

This application captures text from a target window, performs OCR using
MeikiOCR, translates using Sugoi V4, and displays subtitles in a
transparent overlay.
"""

__version__ = "2.0.0"

# Public API
from .__main__ import main, list_windows

__all__ = ["main", "list_windows", "__version__"]
