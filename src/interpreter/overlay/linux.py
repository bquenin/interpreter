"""Linux-specific overlay configuration using X11 Shape extension."""

import tkinter as tk
from typing import Any, Optional

# Platform constants
# On Linux, capture module already handles title bar exclusion, so no offset needed
TITLE_BAR_HEIGHT = 0
# Helvetica maps to a scalable font on Linux via Tk
FONT_FAMILY = "Helvetica"

# X11 shape extension support
_xlib_available = False
_display = None

try:
    from Xlib import display
    from Xlib.ext import shape
    _xlib_available = True
except ImportError:
    pass


class LinuxWindowHandle:
    """Wrapper for Linux window state needed for shape masking."""

    def __init__(self, root: tk.Tk, toplevel_window: Any, xdisplay: Any):
        self.root = root
        self.toplevel = toplevel_window
        self.display = xdisplay
        self.shape_applied = False


def setup_transparency(root: tk.Tk) -> tuple[str, str]:
    """Configure transparency for Linux/X11.

    Uses X11 Shape extension for true transparency (non-rectangular windows).
    For XWayland/Wayland, also tries compositor-based transparency hints.

    Args:
        root: The Tkinter root window.

    Returns:
        Tuple of (transparent_color, label_transparent_bg).
    """
    # Background color - will be hidden by shape mask in inplace mode
    transparent_color = "#010101"
    root.config(bg=transparent_color)

    # Try to set transparent color attribute (some compositors support this)
    try:
        root.attributes('-transparentcolor', transparent_color)
    except Exception:
        pass  # Not supported on this platform/compositor

    return transparent_color, transparent_color


def setup_window(root: tk.Tk, mode: str) -> Optional[LinuxWindowHandle]:
    """Configure Linux-specific window behavior.

    Args:
        root: The Tkinter root window.
        mode: Current overlay mode ("banner" or "inplace").

    Returns:
        LinuxWindowHandle for shape mask operations, or None if unavailable.
    """
    global _display
    from .. import log
    logger = log.get_logger()

    logger.debug("setup_window called", mode=mode, xlib_available=_xlib_available)

    # Force the window to be visible and update
    root.update_idletasks()
    root.deiconify()
    root.lift()
    root.focus_force()

    if not _xlib_available:
        logger.debug("setup_window: xlib not available")
        return None

    try:
        # Get X11 display and window
        window_id = root.winfo_id()
        _display = display.Display()
        window = _display.create_resource_object('window', window_id)

        # Walk up to find the true toplevel window (Tk creates nested windows)
        toplevel = window
        while True:
            geom = toplevel.query_tree()
            if geom.parent == _display.screen().root:
                break
            toplevel = geom.parent

        logger.debug("setup_window: found toplevel", tk_id=window_id, toplevel_id=toplevel.id)

        # Check if shape extension is available
        try:
            from Xlib.ext import shape
            # Try to query existing shape to verify extension works
            shape.query_extents(toplevel)
            logger.debug("setup_window: shape extension available")
        except Exception as e:
            logger.debug("setup_window: shape extension check failed", error=str(e))

        # Don't set DOCK window type - it can interfere with shape masks
        # Window type is left as default

        return LinuxWindowHandle(root, toplevel, _display)

    except Exception as e:
        logger.debug("setup_window: failed", error=str(e))
        return None


def set_click_through(window_handle: Any, enabled: bool) -> None:
    """Set click-through behavior on Linux.

    Args:
        window_handle: LinuxWindowHandle from setup_window.
        enabled: Whether to enable click-through.

    Note:
        On Linux, click-through is achieved via the X11 Shape extension
        input mask. Call update_shape_mask() to apply the actual regions.
    """
    # Click-through state is managed via shape masks in update_shape_mask()
    pass


def update_shape_mask(window_handle: Any, labels: list[tk.Label]) -> None:
    """Update X11 shape mask to make only label areas visible and clickable.

    Args:
        window_handle: LinuxWindowHandle from setup_window.
        labels: List of Tkinter Label widgets to make visible.
    """
    from .. import log
    logger = log.get_logger()

    if not _xlib_available:
        logger.debug("shape mask: xlib not available")
        return

    if window_handle is None:
        logger.debug("shape mask: no window handle")
        return

    if not isinstance(window_handle, LinuxWindowHandle):
        logger.debug("shape mask: invalid window handle type")
        return

    try:
        # Build list of rectangles from label positions
        rects = []
        for label in labels:
            lx = label.winfo_x()
            ly = label.winfo_y()
            lw = label.winfo_width()
            lh = label.winfo_height()
            if lw > 1 and lh > 1:  # Only include properly sized labels
                rects.append((lx, ly, lw, lh))

        # Empty rects = hide entire window (transparent)
        # We use a 1x1 rect at -1,-1 (off-screen) to make window "exist" but invisible
        if not rects:
            rects = [(-1, -1, 1, 1)]

        logger.debug("shape mask: applying", num_rects=len(rects), rects=rects[:3])

        # Apply bounding shape (what pixels are visible)
        window_handle.toplevel.shape_rectangles(
            shape.SO.Set, shape.SK.Bounding, 0, 0, 0, rects
        )

        # Apply input shape (what pixels receive mouse events)
        window_handle.toplevel.shape_rectangles(
            shape.SO.Set, shape.SK.Input, 0, 0, 0, rects
        )

        window_handle.display.sync()
        window_handle.shape_applied = True
        logger.debug("shape mask: applied successfully")

    except Exception as e:
        logger.debug("shape mask: failed", error=str(e))


def reset_shape_mask(window_handle: Any) -> None:
    """Reset X11 shape mask to show the full window (for banner mode).

    Args:
        window_handle: LinuxWindowHandle from setup_window.
    """
    if not _xlib_available or window_handle is None:
        return

    if not isinstance(window_handle, LinuxWindowHandle):
        return

    try:
        # Reset to full window by setting shape to None
        # This removes the shape mask entirely
        window_handle.toplevel.shape_mask(
            shape.SO.Set, shape.SK.Bounding, 0, 0, 0  # 0 = X.NONE
        )
        window_handle.toplevel.shape_mask(
            shape.SO.Set, shape.SK.Input, 0, 0, 0
        )
        window_handle.display.sync()
        window_handle.shape_applied = False

    except Exception:
        pass
