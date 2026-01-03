"""Windows-specific overlay configuration."""

import tkinter as tk
from typing import Any, Optional

# Platform constants
TITLE_BAR_HEIGHT = 32
FONT_FAMILY = "Arial"


def setup_transparency(root: tk.Tk) -> tuple[str, str]:
    """Configure transparency for Windows.

    Uses the -transparentcolor attribute for true transparency.

    Args:
        root: The Tkinter root window.

    Returns:
        Tuple of (transparent_color, label_transparent_bg).
    """
    transparent_color = "#010101"  # Near-black, unlikely to be used
    root.attributes("-transparentcolor", transparent_color)
    root.config(bg=transparent_color)
    return transparent_color, transparent_color


def setup_window(root: tk.Tk, mode: str) -> Optional[Any]:
    """Configure Windows-specific window behavior.

    Args:
        root: The Tkinter root window.
        mode: Current overlay mode ("banner" or "inplace").

    Returns:
        None (no platform-specific window handle on Windows).
    """
    # No special window configuration needed on Windows
    return None


def set_click_through(window_handle: Any, enabled: bool) -> None:
    """Set click-through behavior on Windows.

    Args:
        window_handle: Platform window handle (unused on Windows).
        enabled: Whether to enable click-through.

    Note:
        Click-through could be implemented via win32 extended styles,
        but is not currently supported.
    """
    pass  # Not implemented on Windows
