"""Interpreter - Offline screen translator for Japanese retro games.

This application captures text from a target window, performs OCR using
MeikiOCR, translates using Sugoi V4, and displays subtitles in a
transparent overlay.
"""

__version__ = "2.2.0"


def main():
    """Entry point for the application."""
    from .gui import run
    return run()


__all__ = ["main", "__version__"]
