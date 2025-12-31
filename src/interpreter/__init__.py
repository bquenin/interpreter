"""Interpreter - Offline screen translator for Japanese retro games.

This application captures text from a target window, performs OCR using
MeikiOCR, translates using Sugoi V4, and displays subtitles in a
transparent overlay.
"""

import time as _t
_s = _t.perf_counter()
print("[0ms] Package loading...", flush=True)

__version__ = "0.1.0"
__commit__ = "d18cddb"  # Short commit hash, updated on release

# Public API
from .__main__ import main, list_windows

print(f"[{(_t.perf_counter() - _s)*1000:.0f}ms] Package loaded", flush=True)

__all__ = ["main", "list_windows", "__version__", "__commit__"]
