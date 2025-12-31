"""Linux-specific overlay configuration."""

import tkinter as tk
from typing import Any, Optional

# Platform constants
TITLE_BAR_HEIGHT = 30
FONT_FAMILY = "DejaVu Sans"


def setup_transparency(root: tk.Tk) -> tuple[str, str]:
    """Configure transparency for Linux/X11.

    Uses color-key transparency. True transparency requires compositor support.

    Args:
        root: The Tkinter root window.

    Returns:
        Tuple of (transparent_color, label_transparent_bg).
    """
    transparent_color = "#010101"  # Near-black, unlikely to be used
    root.config(bg=transparent_color)
    return transparent_color, transparent_color


def setup_window(root: tk.Tk, mode: str) -> Optional[Any]:
    """Configure Linux-specific window behavior.

    Args:
        root: The Tkinter root window.
        mode: Current overlay mode ("banner" or "inplace").

    Returns:
        None (no platform-specific window handle on Linux).
    """
    # No special window configuration needed on Linux
    return None


def set_click_through(window_handle: Any, enabled: bool) -> None:
    """Set click-through behavior on Linux.

    Args:
        window_handle: Platform window handle (unused on Linux).
        enabled: Whether to enable click-through.

    Note:
        Click-through is not supported on Linux/X11.
    """
    pass  # Not supported on Linux
