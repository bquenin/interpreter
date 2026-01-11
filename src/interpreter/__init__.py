"""Interpreter - Offline screen translator for Japanese retro games.

This application captures text from a target window, performs OCR using
MeikiOCR, translates using Sugoi V4, and displays subtitles in a
transparent overlay.
"""

import faulthandler
import signal

# Enable faulthandler to dump thread stacks on SIGUSR1 (Unix only)
# Usage: kill -USR1 <pid>  (find pid with: pgrep -f interpreter)
if hasattr(signal, "SIGUSR1"):
    faulthandler.register(signal.SIGUSR1, all_threads=True)

from importlib.metadata import version

__version__ = version("interpreter-v2")


def main():
    """Entry point for the application."""
    from .gui import run

    return run()


__all__ = ["__version__", "main"]
