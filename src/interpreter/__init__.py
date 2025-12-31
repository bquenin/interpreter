"""Interpreter - Offline screen translator for Japanese retro games.

This application captures text from a target window, performs OCR using
MeikiOCR, translates using Sugoi V4, and displays subtitles in a
transparent overlay.
"""

__version__ = "2.0.0"
__commit__ = "165ec22"  # Short commit hash, updated on release

# Public API
from .__main__ import main, list_windows

__all__ = ["main", "list_windows", "__version__", "__commit__"]
