"""macOS-specific overlay configuration."""

import tkinter as tk
from typing import Any, Optional

# Platform constants
TITLE_BAR_HEIGHT = 30
FONT_FAMILY = "Helvetica"


def setup_transparency(root: tk.Tk) -> tuple[str, str]:
    """Configure transparency for macOS.

    Uses native macOS transparency with systemTransparent.

    Args:
        root: The Tkinter root window.

    Returns:
        Tuple of (transparent_color, label_transparent_bg).
    """
    root.attributes("-transparent", True)
    root.config(bg="systemTransparent")
    return "systemTransparent", "systemTransparent"


def setup_window(root: tk.Tk, mode: str) -> Optional[Any]:
    """Configure macOS-specific window behavior using AppKit.

    Sets up:
    - Window appears on all spaces (desktops)
    - Stationary behavior (doesn't move with space switches)
    - Click-through in inplace mode

    Args:
        root: The Tkinter root window.
        mode: Current overlay mode ("banner" or "inplace").

    Returns:
        The NSWindow object if found, None otherwise.
    """
    try:
        from AppKit import (
            NSApplication,
            NSWindowCollectionBehaviorCanJoinAllSpaces,
            NSWindowCollectionBehaviorStationary,
        )

        root.update_idletasks()
        ns_app = NSApplication.sharedApplication()

        for ns_window in ns_app.windows():
            title = ns_window.title() or ""
            if "Interpreter" in title:
                behavior = (
                    NSWindowCollectionBehaviorCanJoinAllSpaces |
                    NSWindowCollectionBehaviorStationary
                )
                ns_window.setCollectionBehavior_(behavior)

                # Make click-through in inplace mode
                if mode == "inplace":
                    ns_window.setIgnoresMouseEvents_(True)

                return ns_window
    except Exception:
        pass

    return None


def set_click_through(window_handle: Any, enabled: bool) -> None:
    """Set click-through behavior on macOS.

    Args:
        window_handle: The NSWindow object.
        enabled: Whether to enable click-through.
    """
    if window_handle is None:
        return

    try:
        window_handle.setIgnoresMouseEvents_(enabled)
    except Exception:
        pass
