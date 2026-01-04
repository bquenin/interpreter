"""Interpreter - Offline screen translator for Japanese retro games.

This application captures text from a target window, performs OCR using
MeikiOCR, translates using Sugoi V4, and displays subtitles in a
transparent overlay.
"""

from importlib.metadata import version

__version__ = version("interpreter-v2")


def main():
    """Entry point for the application."""
    from .gui import run

    return run()


__all__ = ["__version__", "main"]
