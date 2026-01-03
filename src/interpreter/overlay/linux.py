"""Linux overlay implementation using Tkinter with X11 shape extension.

Why Tkinter instead of Qt on Linux?
-----------------------------------
Qt overlays on Linux/X11 have issues with stay-on-top behavior, click-through
transparency, and window positioning over fullscreen applications. Tkinter with
the X11 shape extension provides reliable overlay behavior.

Architecture
------------
This module provides BannerOverlay and InplaceOverlay wrapper classes that expose
the same API as the Qt-based overlays in overlay.py. This allows main_window.py
to use identical code regardless of platform:

    main_window.py
        ↓
    BannerOverlay / InplaceOverlay  (Qt-compatible API)
        ↓
    _get_or_create_overlay()        (singleton factory)
        ↓
    Overlay                         (Tkinter core, manages both windows)

Why wrappers around a singleton?
--------------------------------
Tkinter has a fundamental constraint: only one Tk() root window can exist per
process. Both banner and inplace modes need to share this root. The Overlay class
manages both windows internally, while the wrapper classes provide the expected
interface (separate BannerOverlay and InplaceOverlay instances that main_window.py
can call show/hide on independently).

The singleton pattern with _get_or_create_overlay() ensures both wrappers share
the same underlying Tkinter instance.

Event loop integration
----------------------
Since the main application uses Qt, we pump Tkinter events from a Qt timer
(_pump_tk_events) rather than running Tk's mainloop.
"""

import tkinter as tk
from tkinter import font as tkfont
from typing import Any, Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from .. import log
from .base import BANNER_HEIGHT, BANNER_BOTTOM_MARGIN

logger = log.get_logger()

# =============================================================================
# X11 Shape Extension Support (for click-through transparency)
# =============================================================================

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

    def __init__(self, toplevel_window: Any, xdisplay: Any):
        self.toplevel = toplevel_window
        self.display = xdisplay


def _setup_transparency(root: tk.Tk) -> None:
    """Configure transparency for Linux/X11."""
    transparent_color = "#010101"
    root.config(bg=transparent_color)

    try:
        root.attributes('-transparentcolor', transparent_color)
    except Exception:
        pass


def _setup_window(root: tk.Tk, mode: str) -> Optional[LinuxWindowHandle]:
    """Configure Linux-specific window behavior.

    Returns:
        LinuxWindowHandle for shape mask operations, or None if unavailable.
    """
    global _display

    logger.debug("setup_window called", mode=mode, xlib_available=_xlib_available)

    root.update_idletasks()
    root.deiconify()
    root.lift()
    root.focus_force()

    if not _xlib_available:
        logger.debug("setup_window: xlib not available")
        return None

    try:
        window_id = root.winfo_id()
        _display = display.Display()
        window = _display.create_resource_object('window', window_id)

        # Walk up to find the true toplevel window
        toplevel = window
        while True:
            geom = toplevel.query_tree()
            if geom.parent == _display.screen().root:
                break
            toplevel = geom.parent

        logger.debug("setup_window: found toplevel", tk_id=window_id, toplevel_id=toplevel.id)

        try:
            shape.query_extents(toplevel)
            logger.debug("setup_window: shape extension available")
        except Exception as e:
            logger.debug("setup_window: shape extension check failed", error=str(e))

        return LinuxWindowHandle(toplevel, _display)

    except Exception as e:
        logger.debug("setup_window: failed", error=str(e))
        return None


def _update_shape_mask(window_handle: Any, labels: list[tk.Label]) -> None:
    """Update X11 shape mask to make only label areas visible and clickable."""
    if not _xlib_available or window_handle is None:
        return

    if not isinstance(window_handle, LinuxWindowHandle):
        return

    try:
        rects = []
        for label in labels:
            lx = label.winfo_x()
            ly = label.winfo_y()
            lw = label.winfo_width()
            lh = label.winfo_height()
            if lw > 1 and lh > 1:
                rects.append((lx, ly, lw, lh))

        if not rects:
            rects = [(-1, -1, 1, 1)]

        window_handle.toplevel.shape_rectangles(
            shape.SO.Set, shape.SK.Bounding, 0, 0, 0, rects
        )
        window_handle.toplevel.shape_rectangles(
            shape.SO.Set, shape.SK.Input, 0, 0, 0, rects
        )

        window_handle.display.flush()

    except Exception as e:
        logger.debug("shape mask: failed", error=str(e))

# =============================================================================
# Core Tkinter Overlay Class
# =============================================================================

class Overlay:
    """A transparent, always-on-top window for displaying translated text.

    Uses two separate Tk windows:
    - Banner window: Fixed at bottom of screen, draggable, opaque background
    - Inplace window: Follows game window, transparent, text at OCR positions
    """

    def __init__(
        self,
        font_family: str = "Helvetica",
        font_size: int = 40,
        font_color: str = "#FFFFFF",
        background_color: str = "#404040",
    ):
        self.font_family = font_family
        self.font_size = font_size
        self.font_color = font_color
        self.background_color = background_color

        # Banner window components
        self._banner_root: Optional[tk.Tk] = None
        self._banner_frame: Optional[tk.Frame] = None
        self._banner_label: Optional[tk.Label] = None
        self._banner_font: Optional[tkfont.Font] = None

        # Inplace window components
        self._inplace_root: Optional[tk.Toplevel] = None
        self._inplace_labels: list[tk.Label] = []
        self._inplace_font: Optional[tkfont.Font] = None
        self._inplace_handle = None

        self._current_text: str = ""
        self._paused: bool = False
        self._mode: str = "banner"

        # Bounds tracking
        self._display_bounds: Optional[dict] = None
        self._window_bounds: Optional[dict] = None
        self._image_size: tuple[int, int] = (0, 0)
        self._retina_scale: float = 1.0
        self._content_offset: tuple[int, int] = (0, 0)
        self._last_regions: list[tuple[str, dict]] = []

        # Drag state
        self._drag_start_x: int = 0
        self._drag_start_y: int = 0

    def create(self, display_bounds: dict, window_bounds: dict, image_size: tuple[int, int], mode: str = "banner", content_offset: tuple[int, int] = (0, 0)):
        """Create and configure both overlay windows."""
        self._display_bounds = display_bounds
        self._window_bounds = window_bounds.copy()
        self._image_size = image_size
        self._content_offset = content_offset
        self._mode = mode

        if window_bounds["width"] > 0:
            self._retina_scale = image_size[0] / window_bounds["width"]

        self._create_banner_window()
        self._create_inplace_window()

        if mode == "banner":
            self._show_banner()
        else:
            self._show_inplace()

    def _create_banner_window(self):
        """Create the banner mode window."""
        self._banner_root = tk.Tk()
        self._banner_root.title("Interpreter Banner")
        self._banner_root.overrideredirect(True)
        self._banner_root.attributes("-topmost", True)

        _setup_transparency(self._banner_root)

        self._banner_frame = tk.Frame(
            self._banner_root,
            bg=self.background_color,
            padx=20,
            pady=10,
        )
        self._banner_frame.pack(expand=True, fill=tk.BOTH)

        self._banner_font = tkfont.Font(family=self.font_family, size=self.font_size, weight="bold")

        self._banner_label = tk.Label(
            self._banner_frame,
            text="",
            font=self._banner_font,
            fg=self.font_color,
            bg=self.background_color,
            justify=tk.CENTER,
        )
        self._banner_label.pack(expand=True)

        self._banner_frame.bind("<Button-1>", self._start_drag)
        self._banner_frame.bind("<B1-Motion>", self._on_drag)
        self._banner_label.bind("<Button-1>", self._start_drag)
        self._banner_label.bind("<B1-Motion>", self._on_drag)

        self._position_banner()

    def _create_inplace_window(self):
        """Create the inplace mode window."""
        self._inplace_root = tk.Toplevel(self._banner_root)
        self._inplace_root.title("Interpreter Inplace")
        self._inplace_root.overrideredirect(True)
        self._inplace_root.attributes("-topmost", True)

        _setup_transparency(self._inplace_root)
        self._inplace_handle = _setup_window(self._inplace_root, "inplace")

        self._inplace_font = tkfont.Font(family=self.font_family, size=self.font_size, weight="bold")

        self._inplace_root.withdraw()

    def _position_banner(self):
        """Position the banner window at bottom of display."""
        if self._display_bounds:
            width = self._display_bounds["width"]
            height = BANNER_HEIGHT
            x = self._display_bounds["x"]
            y = self._display_bounds["y"] + self._display_bounds["height"] - height - BANNER_BOTTOM_MARGIN
        else:
            width = self._banner_root.winfo_screenwidth()
            height = BANNER_HEIGHT
            x = 0
            y = self._banner_root.winfo_screenheight() - height - BANNER_BOTTOM_MARGIN

        self._banner_label.config(wraplength=width - 60)
        self._banner_root.geometry(f"{width}x{height}+{x}+{y}")
        self._banner_root.update_idletasks()

    def set_mode(self, mode: str):
        """Switch between banner and inplace modes."""
        if mode == self._mode:
            return
        self._mode = mode
        if mode == "banner":
            self._show_banner()
        else:
            self._show_inplace()

    def _show_banner(self):
        """Show banner window, hide inplace window."""
        if self._inplace_root:
            self._inplace_root.withdraw()
        if self._banner_root:
            # Set text and resize BEFORE showing to avoid flicker
            self._position_banner()
            if self._current_text and self._banner_label:
                self._banner_label.config(text=self._current_text)
                self._resize_banner_to_fit()
            # Now show the window at correct size
            self._banner_root.deiconify()
            self._banner_root.lift()

    def _show_inplace(self):
        """Show inplace window, hide banner window."""
        if self._banner_root:
            self._banner_root.withdraw()
        if self._inplace_root:
            # Render regions BEFORE showing to avoid flicker
            self._render_inplace_regions()
            self._inplace_root.lift()

    def adjust_font_size(self, delta: int):
        """Adjust the font size by delta pixels."""
        if delta == 0:
            return
        self.font_size += delta

        if self._banner_font:
            self._banner_font.configure(size=self.font_size)
        if self._inplace_font:
            self._inplace_font.configure(size=self.font_size)

    def set_colors(self, font_color: str, background_color: str):
        """Update font and background colors."""
        self.font_color = font_color
        self.background_color = background_color

        # Update banner
        if self._banner_frame:
            self._banner_frame.config(bg=background_color)
        if self._banner_label:
            self._banner_label.config(fg=font_color, bg=background_color)

        # Update inplace labels
        for label in self._inplace_labels:
            label.config(fg=font_color, bg=background_color)

    def update_position(self, window_bounds: dict, display_bounds: dict = None, image_size: tuple[int, int] = None, content_offset: tuple[int, int] = None):
        """Update overlay position to follow the game window."""
        window_changed = window_bounds != self._window_bounds
        if window_changed:
            self._window_bounds = window_bounds.copy()

        if content_offset is not None and content_offset != self._content_offset:
            self._content_offset = content_offset

        image_changed = image_size and image_size != self._image_size
        if image_changed:
            self._image_size = image_size

        if image_size and window_bounds["width"] > 0:
            self._retina_scale = image_size[0] / window_bounds["width"]

        display_changed = display_bounds and display_bounds != self._display_bounds
        if display_changed:
            self._display_bounds = display_bounds.copy()

        if self._mode == "inplace" and (window_changed or image_changed):
            self._render_inplace_regions()
        elif self._mode == "banner" and display_changed:
            self._position_banner()

    def _resize_banner_to_fit(self):
        """Resize banner window to fit current text content."""
        if not self._banner_root or not self._banner_label:
            return

        self._banner_root.update_idletasks()
        required_height = self._banner_label.winfo_reqheight() + 30
        current_width = self._banner_root.winfo_width()
        current_x = self._banner_root.winfo_x()
        current_height = self._banner_root.winfo_height()
        current_y = self._banner_root.winfo_y()

        current_bottom = current_y + current_height
        new_y = current_bottom - required_height

        self._banner_root.geometry(f"{current_width}x{required_height}+{current_x}+{new_y}")

    def update_text(self, text: str):
        """Update the displayed text (banner mode)."""
        if self._banner_label is None or self._paused:
            return

        self._current_text = text
        self._banner_label.config(text=text)

        if self._mode == "banner":
            self._resize_banner_to_fit()

    def _start_drag(self, event):
        """Start dragging the banner window."""
        self._drag_start_x = event.x
        self._drag_start_y = event.y

    def _on_drag(self, event):
        """Handle banner window dragging."""
        x = self._banner_root.winfo_x() + event.x - self._drag_start_x
        y = self._banner_root.winfo_y() + event.y - self._drag_start_y
        self._banner_root.geometry(f"+{x}+{y}")

    def update_regions(self, regions: list[tuple[str, dict]]):
        """Update the displayed text regions (inplace mode)."""
        if self._paused:
            return

        self._last_regions = [(text, bbox.copy()) for text, bbox in regions]

        if self._mode == "inplace":
            self._render_inplace_regions()

    def _render_inplace_regions(self):
        """Render all text regions using fitted window approach."""
        if self._inplace_root is None:
            return

        if not self._last_regions:
            self._inplace_root.withdraw()
            return

        min_x = float('inf')
        min_y = float('inf')
        max_x = 0
        max_y = 0

        for text, bbox in self._last_regions:
            if not text or not bbox:
                continue
            x, y = bbox["x"], bbox["y"]
            w, h = bbox["width"], bbox.get("height", 80)
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x + w)
            max_y = max(max_y, y + h)

        if min_x == float('inf'):
            self._inplace_root.withdraw()
            return

        padding = 10
        min_x = max(0, min_x - padding)
        min_y = max(0, min_y - padding)
        max_x += padding
        max_y += padding

        scale = self._retina_scale if self._retina_scale > 0 else 1.0
        min_x_screen = min_x / scale
        min_y_screen = min_y / scale
        max_x_screen = max_x / scale
        max_y_screen = max_y / scale

        win_x = int(self._window_bounds["x"] + self._content_offset[0] + min_x_screen)
        win_y = int(self._window_bounds["y"] + self._content_offset[1] + min_y_screen)
        win_w = int(max_x_screen - min_x_screen)
        win_h = int(max_y_screen - min_y_screen)

        visible_labels = []
        for i, (text, bbox) in enumerate(self._last_regions):
            if not text or not bbox:
                continue

            label = self._get_or_create_inplace_label(i)

            rel_x = (bbox["x"] - min_x) / scale
            rel_y = (bbox["y"] - min_y) / scale
            width = bbox["width"] / scale

            label.config(text=text, font=self._inplace_font, wraplength=int(width))
            label.place(x=int(rel_x), y=int(rel_y))
            visible_labels.append(label)

        # Hide unused labels (without hiding active ones to avoid flicker)
        for label in self._inplace_labels:
            if label not in visible_labels:
                label.place_forget()

        self._inplace_root.deiconify()
        self._inplace_root.wm_minsize(1, 1)
        self._inplace_root.wm_maxsize(win_w + 100, win_h + 100)
        self._inplace_root.geometry(f"{win_w}x{win_h}+{win_x}+{win_y}")
        self._inplace_root.update_idletasks()

        if _xlib_available:
            _update_shape_mask(self._inplace_handle, visible_labels)

    def _get_or_create_inplace_label(self, index: int) -> tk.Label:
        """Get an existing inplace label or create a new one."""
        while len(self._inplace_labels) <= index:
            label = tk.Label(
                self._inplace_root,
                text="",
                font=self._inplace_font,
                fg=self.font_color,
                bg=self.background_color,
                padx=4,
                pady=2,
                justify=tk.LEFT,
                anchor="nw",
            )
            self._inplace_labels.append(label)
        return self._inplace_labels[index]

    def pause(self):
        """Pause the overlay (hides both windows)."""
        if self._paused:
            return
        self._paused = True
        if self._banner_root:
            self._banner_root.withdraw()
        if self._inplace_root:
            self._inplace_root.withdraw()

    def resume(self):
        """Resume the overlay (shows appropriate window)."""
        if not self._paused:
            return
        self._paused = False
        if self._mode == "banner":
            self._show_banner()
        else:
            self._show_inplace()

    def quit(self):
        """Close both windows and quit."""
        if self._inplace_root:
            self._inplace_root.destroy()
        if self._banner_root:
            self._banner_root.quit()
            self._banner_root.destroy()

    def update(self):
        """Process pending Tkinter events."""
        if self._banner_root:
            self._banner_root.update()

    @property
    def paused(self) -> bool:
        """Check if overlay is paused."""
        return self._paused

    @property
    def is_running(self) -> bool:
        """Check if the overlay is still running."""
        try:
            if self._banner_root:
                self._banner_root.winfo_exists()
                return True
        except tk.TclError:
            pass
        return False

    @property
    def mode(self) -> str:
        """Get the current mode."""
        return self._mode


# =============================================================================
# Qt-Compatible Wrapper Classes
# =============================================================================

# Shared Tkinter overlay instance
_tk_overlay: Optional[Overlay] = None
_tk_timer: Optional[QTimer] = None
_initialized = False


def _get_or_create_overlay(font_family: str, font_size: int, font_color: str, background_color: str) -> Overlay:
    """Get or create the shared Tkinter overlay instance."""
    global _tk_overlay, _tk_timer, _initialized

    if _tk_overlay is None:
        _tk_overlay = Overlay(
            font_family=font_family,
            font_size=font_size,
            font_color=font_color,
            background_color=background_color,
        )

    if not _initialized:
        screen = QApplication.primaryScreen()
        screen_geom = screen.geometry()
        display_bounds = {
            "x": screen_geom.x(),
            "y": screen_geom.y(),
            "width": screen_geom.width(),
            "height": screen_geom.height(),
        }

        _tk_overlay.create(
            display_bounds=display_bounds,
            window_bounds=display_bounds.copy(),
            image_size=(display_bounds["width"], display_bounds["height"]),
            mode="banner",
        )

        _tk_overlay.pause()

        _tk_timer = QTimer()
        _tk_timer.timeout.connect(_pump_tk_events)
        _tk_timer.start(16)

        _initialized = True

    return _tk_overlay


def _pump_tk_events():
    """Pump Tkinter events from Qt event loop."""
    global _tk_overlay
    if _tk_overlay and _tk_overlay.is_running:
        try:
            _tk_overlay.update()
        except Exception:
            pass


def _close_overlay():
    """Close the shared overlay instance."""
    global _tk_overlay, _tk_timer, _initialized
    if _tk_overlay:
        _tk_overlay.quit()
        _tk_overlay = None
    if _tk_timer:
        _tk_timer.stop()
        _tk_timer = None
    _initialized = False


class _OverlayWrapper:
    """Base class for Qt-compatible overlay wrappers.

    Provides common functionality for font size, colors, and lifecycle management.
    Subclasses must define _mode as a class attribute.
    """

    _mode: str  # Must be defined as class attribute by subclass

    def __init__(
        self,
        font_family: str,
        font_size: int,
        font_color: str,
        background_color: str,
    ):
        self._font_family = font_family
        self._font_size = font_size
        self._font_color = font_color
        self._background_color = background_color
        self._visible = False

        _get_or_create_overlay(font_family, font_size, font_color, background_color)

    def set_font_size(self, size: int):
        """Update the font size."""
        self._font_size = size
        if _tk_overlay:
            delta = size - _tk_overlay.font_size
            if delta != 0:
                _tk_overlay.adjust_font_size(delta)

    def set_colors(self, font_color: str, background_color: str):
        """Update the colors."""
        self._font_color = font_color
        self._background_color = background_color
        if _tk_overlay:
            _tk_overlay.set_colors(font_color, background_color)

    @property
    def font_size(self) -> int:
        return self._font_size

    def show(self):
        """Show the overlay."""
        if _tk_overlay and not self._visible:
            _tk_overlay.set_mode(self._mode)
            _tk_overlay.resume()
            self._visible = True

    def hide(self):
        """Hide the overlay."""
        if _tk_overlay and self._visible:
            _tk_overlay.pause()
            self._visible = False

    def close(self):
        """Close the overlay."""
        _close_overlay()


class BannerOverlay(_OverlayWrapper):
    """Banner-style overlay at bottom of screen.

    A draggable subtitle bar that displays translated text.
    This is a wrapper around the Tkinter-based overlay for Linux.
    """

    _mode = "banner"

    def __init__(
        self,
        font_family: str = "Helvetica",
        font_size: int = 24,
        font_color: str = "#FFFFFF",
        background_color: str = "#404040",
    ):
        super().__init__(font_family, font_size, font_color, background_color)

    def set_text(self, text: str):
        """Update the displayed text."""
        if _tk_overlay:
            _tk_overlay.update_text(text)


class InplaceOverlay(_OverlayWrapper):
    """Transparent overlay for inplace text display.

    A click-through overlay that positions translated text
    directly over the original game text.
    This is a wrapper around the Tkinter-based overlay for Linux.
    """

    _mode = "inplace"

    def __init__(
        self,
        font_family: str = "Helvetica",
        font_size: int = 18,
        font_color: str = "#FFFFFF",
        background_color: str = "#000000",
    ):
        super().__init__(font_family, font_size, font_color, background_color)
        self._last_bounds: dict = {}
        self._content_offset: tuple[int, int] = (0, 0)

    def set_regions(self, regions: list[tuple[str, dict]], content_offset: tuple[int, int] = (0, 0)):
        """Update text regions."""
        if _tk_overlay:
            offset_changed = content_offset != self._content_offset
            self._content_offset = content_offset

            if offset_changed and self._last_bounds:
                self._update_position_with_offset(self._last_bounds)

            _tk_overlay.update_regions(regions)

    def _update_position_with_offset(self, bounds: dict):
        """Internal method to update position with current content offset."""
        screen = QApplication.primaryScreen()
        scale = screen.devicePixelRatio()

        image_size = (int(bounds["width"] * scale), int(bounds["height"] * scale))

        _tk_overlay.update_position(
            bounds,
            image_size=image_size,
            content_offset=self._content_offset
        )

    def position_over_window(self, bounds: dict):
        """Position overlay to cover a window."""
        if _tk_overlay:
            self._last_bounds = bounds.copy()
            self._update_position_with_offset(bounds)

    def clear_regions(self):
        """Clear all displayed text regions."""
        if _tk_overlay:
            _tk_overlay.update_regions([])
