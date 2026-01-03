"""Overlay windows for displaying subtitles in banner or inplace mode.

Uses two separate windows to avoid shape mask reset issues:
- Banner window: Fixed position, draggable, no shape mask
- Inplace window: Follows game window, shape mask for click-through
"""

import platform
import tkinter as tk
from tkinter import font as tkfont
from typing import Optional

from ... import log

# Platform detection
_system = platform.system()
_is_windows = _system == "Windows"

# Debug flag - set via Overlay.set_debug()
_debug = False
_logger = log.get_logger()

def _debug_log(msg: str, **kwargs):
    """Log debug messages if debug mode is enabled."""
    if _debug:
        _logger.debug(msg, **kwargs)

# Platform-specific shape mask functions (Linux only)
_update_shape_mask = None

if _system == "Darwin":
    from .macos import TITLE_BAR_HEIGHT, FONT_FAMILY, setup_transparency, setup_window, set_click_through
elif _system == "Windows":
    from .windows import TITLE_BAR_HEIGHT, FONT_FAMILY, setup_transparency, setup_window, set_click_through
elif _system == "Linux":
    from .linux import TITLE_BAR_HEIGHT, FONT_FAMILY, setup_transparency, setup_window, set_click_through
    from .linux import update_shape_mask as _update_shape_mask
else:
    # Fallback for unsupported platforms
    TITLE_BAR_HEIGHT = 30
    FONT_FAMILY = "Helvetica"
    def setup_transparency(root): return ("#010101", "#010101")
    def setup_window(root, mode): return None
    def set_click_through(handle, enabled): pass

# Overlay layout constants
DEFAULT_RETINA_SCALE = 2.0      # Default Retina display scale factor
BANNER_HEIGHT = 100             # Default banner overlay height in points
BANNER_BOTTOM_MARGIN = 50       # Gap between banner and screen bottom
MIN_FONT_SIZE = 8               # Minimum allowed font size
MAX_FONT_SIZE = 72              # Maximum allowed font size


class Overlay:
    """A transparent, always-on-top window for displaying translated text.

    Uses two separate Tk windows:
    - Banner window: Fixed at bottom of screen, draggable, opaque background
    - Inplace window: Follows game window, transparent, text at OCR positions

    This design avoids X11 shape mask reset issues when switching modes.
    """

    # -------------------------------------------------------------------------
    # Initialization
    # -------------------------------------------------------------------------

    def __init__(
        self,
        font_size: int = 40,
        font_color: str = "#FFFFFF",
        background_color: str = "#404040",
    ):
        """Initialize the overlay.

        Args:
            font_size: Font size in pixels (used in banner mode).
            font_color: Font color as hex string (e.g., "#FFFFFF").
            background_color: Background color as hex string.
        """
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
        self._inplace_handle = None  # Platform window handle for shape masks

        self._current_text: str = ""
        self._paused: bool = False
        self._mode: str = "banner"  # "banner" or "inplace"

        # Bounds tracking
        self._display_bounds: Optional[dict] = None
        self._window_bounds: Optional[dict] = None
        self._image_size: tuple[int, int] = (0, 0)
        self._retina_scale: float = DEFAULT_RETINA_SCALE
        self._content_offset: tuple[int, int] = (0, 0)
        self._last_regions: list[tuple[str, dict]] = []
        self._debug_borders: list[tk.Frame] = []

    @staticmethod
    def set_debug(enabled: bool):
        """Enable or disable debug output."""
        global _debug
        _debug = enabled

    def create(self, display_bounds: dict, window_bounds: dict, image_size: tuple[int, int], mode: str = "banner", content_offset: tuple[int, int] = (0, 0)):
        """Create and configure both overlay windows.

        Args:
            display_bounds: Dict with x, y, width, height of the display.
            window_bounds: Dict with x, y, width, height of game window.
            image_size: Tuple of (width, height) of captured image for scale detection.
            mode: Initial mode - "banner" or "inplace".
            content_offset: Tuple of (x, y) offset from window bounds to content area.
        """
        _debug_log("overlay create", mode=mode, platform=_system, content_offset=content_offset)

        self._display_bounds = display_bounds
        self._window_bounds = window_bounds.copy()
        self._image_size = image_size
        self._content_offset = content_offset
        self._mode = mode

        # Auto-detect Retina scale
        if window_bounds["width"] > 0:
            self._retina_scale = image_size[0] / window_bounds["width"]

        # Create banner window (main Tk window)
        self._create_banner_window()

        # Create inplace window (Toplevel, hidden initially)
        self._create_inplace_window()

        # Show the appropriate window
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

        # Platform-specific transparency (for background)
        setup_transparency(self._banner_root)

        # Create frame and label
        self._banner_frame = tk.Frame(
            self._banner_root,
            bg=self.background_color,
            padx=20,
            pady=10,
        )
        self._banner_frame.pack(expand=True, fill=tk.BOTH)

        self._banner_font = tkfont.Font(family=FONT_FAMILY, size=self.font_size, weight="bold")

        self._banner_label = tk.Label(
            self._banner_frame,
            text="",
            font=self._banner_font,
            fg=self.font_color,
            bg=self.background_color,
            justify=tk.CENTER,
        )
        self._banner_label.pack(expand=True)

        # Allow dragging
        self._banner_frame.bind("<Button-1>", self._start_drag)
        self._banner_frame.bind("<B1-Motion>", self._on_drag)
        self._banner_label.bind("<Button-1>", self._start_drag)
        self._banner_label.bind("<B1-Motion>", self._on_drag)

        # Position at bottom of display
        self._position_banner()

    def _create_inplace_window(self):
        """Create the inplace mode window."""
        # Use Toplevel so it shares the main loop with banner window
        self._inplace_root = tk.Toplevel(self._banner_root)
        self._inplace_root.title("Interpreter Inplace")
        self._inplace_root.overrideredirect(True)
        self._inplace_root.attributes("-topmost", True)

        # Platform-specific transparency
        self._transparent_color, self._label_transparent_bg = setup_transparency(self._inplace_root)

        # Platform-specific window setup (for shape masks)
        self._inplace_handle = setup_window(self._inplace_root, "inplace")

        # Create font for inplace labels
        self._inplace_font = tkfont.Font(family=FONT_FAMILY, size=self.font_size, weight="bold")

        # Enable click-through
        set_click_through(self._inplace_handle, True)

        # Start hidden (use off-screen on Windows)
        if _is_windows:
            self._inplace_root.geometry("+10000+10000")
        else:
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

    # -------------------------------------------------------------------------
    # Mode Management
    # -------------------------------------------------------------------------

    def set_mode(self, mode: str):
        """Switch between banner and inplace modes.

        Args:
            mode: "banner" or "inplace"
        """
        if mode == self._mode:
            return
        self._mode = mode
        if mode == "banner":
            self._show_banner()
        else:
            self._show_inplace()

    def _hide_window(self, window: tk.Tk | tk.Toplevel):
        """Hide a window in a platform-appropriate way.

        On Windows, withdraw() on the parent Tk window also hides Toplevel children,
        so we move windows off-screen instead.
        """
        if _is_windows:
            # Move off-screen (keeps window "visible" so children work)
            window.geometry("+10000+10000")
        else:
            window.withdraw()

    def _show_banner(self):
        """Show banner window, hide inplace window."""
        _debug_log("showing banner window")
        # Hide inplace
        if self._inplace_root:
            self._hide_window(self._inplace_root)
        # Show banner
        if self._banner_root:
            self._banner_root.deiconify()
            self._position_banner()  # Restore position
            self._banner_root.lift()
            # Restore text if any
            if self._current_text and self._banner_label:
                self._banner_label.config(text=self._current_text)

    def _show_inplace(self):
        """Show inplace window, hide banner window."""
        _debug_log("showing inplace window")
        # Hide banner
        if self._banner_root:
            self._hide_window(self._banner_root)
        # Show inplace and render regions
        if self._inplace_root:
            self._inplace_root.deiconify()
            self._inplace_root.lift()
            self._render_inplace_regions()

    def adjust_font_size(self, delta: int):
        """Adjust the font size by delta pixels.

        Args:
            delta: Amount to change font size (positive or negative).
        """
        new_size = max(MIN_FONT_SIZE, min(MAX_FONT_SIZE, self.font_size + delta))
        if new_size == self.font_size:
            return
        self.font_size = new_size

        # Update both fonts
        if self._banner_font:
            self._banner_font.configure(size=self.font_size)
        if self._inplace_font:
            self._inplace_font.configure(size=self.font_size)

        if self._banner_root:
            self._banner_root.update_idletasks()
        if self._inplace_root:
            self._inplace_root.update_idletasks()

    def update_position(self, window_bounds: dict, display_bounds: dict = None, image_size: tuple[int, int] = None, content_offset: tuple[int, int] = None):
        """Update overlay position to follow the game window.

        Args:
            window_bounds: New window bounds dict with x, y, width, height.
            display_bounds: Optional display bounds for banner mode repositioning.
            image_size: Optional tuple of (width, height) to recalculate retina scale.
            content_offset: Optional tuple of (x, y) offset for content area within window.
        """
        window_changed = window_bounds != self._window_bounds
        if window_changed:
            self._window_bounds = window_bounds.copy()

        if content_offset is not None and content_offset != self._content_offset:
            _debug_log("content offset changed", old=self._content_offset, new=content_offset)
            self._content_offset = content_offset

        image_changed = image_size and image_size != self._image_size
        if image_changed:
            _debug_log("image size changed", old_size=self._image_size, new_size=image_size)
            self._image_size = image_size

        if image_size and window_bounds["width"] > 0:
            self._retina_scale = image_size[0] / window_bounds["width"]

        display_changed = display_bounds and display_bounds != self._display_bounds
        if display_changed:
            self._display_bounds = display_bounds.copy()

        # Update appropriate window
        if self._mode == "inplace" and (window_changed or image_changed):
            self._render_inplace_regions()
        elif self._mode == "banner" and display_changed:
            self._position_banner()

    # -------------------------------------------------------------------------
    # Banner Mode
    # -------------------------------------------------------------------------

    def update_text(self, text: str):
        """Update the displayed text (banner mode).

        Args:
            text: Text to display.
        """
        if self._banner_label is None or self._paused:
            return

        self._current_text = text
        self._banner_label.config(text=text)

        if self._mode == "banner":
            # Auto-resize height based on content
            self._banner_root.update_idletasks()
            required_height = self._banner_label.winfo_reqheight() + 30
            current_width = self._banner_root.winfo_width()
            current_x = self._banner_root.winfo_x()
            current_height = self._banner_root.winfo_height()
            current_y = self._banner_root.winfo_y()

            # Adjust position to keep bottom edge in place
            current_bottom = current_y + current_height
            new_y = current_bottom - required_height

            self._banner_root.geometry(f"{current_width}x{required_height}+{current_x}+{new_y}")

    def _start_drag(self, event):
        """Start dragging the banner window."""
        self._drag_start_x = event.x
        self._drag_start_y = event.y

    def _on_drag(self, event):
        """Handle banner window dragging."""
        x = self._banner_root.winfo_x() + event.x - self._drag_start_x
        y = self._banner_root.winfo_y() + event.y - self._drag_start_y
        self._banner_root.geometry(f"+{x}+{y}")

    # -------------------------------------------------------------------------
    # Inplace Mode
    # -------------------------------------------------------------------------

    def update_regions(self, regions: list[tuple[str, dict]]):
        """Update the displayed text regions (inplace mode).

        Args:
            regions: List of (text, bbox) tuples. Each bbox is a dict with
                     x, y, width, height in image coordinates.
        """
        if self._paused:
            return

        self._last_regions = [(text, bbox.copy()) for text, bbox in regions]

        if self._mode == "inplace":
            self._render_inplace_regions()

    def _render_inplace_regions(self):
        """Render all text regions using fitted window approach."""
        if self._inplace_root is None:
            return

        # Hide all existing labels first
        for label in self._inplace_labels:
            label.place_forget()

        if not self._last_regions:
            # No regions - hide window
            self._hide_window(self._inplace_root)
            return

        # Calculate bounding box of all regions
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
            self._hide_window(self._inplace_root)
            return

        # Add padding (in image coordinates)
        padding = 10
        min_x = max(0, min_x - padding)
        min_y = max(0, min_y - padding)
        max_x += padding
        max_y += padding

        # Convert from image coordinates to screen coordinates
        scale = self._retina_scale if self._retina_scale > 0 else 1.0
        min_x_screen = min_x / scale
        min_y_screen = min_y / scale
        max_x_screen = max_x / scale
        max_y_screen = max_y / scale

        # Calculate window position (relative to game window, in screen coordinates)
        win_x = int(self._window_bounds["x"] + self._content_offset[0] + min_x_screen)
        win_y = int(self._window_bounds["y"] + self._content_offset[1] + min_y_screen)
        win_w = int(max_x_screen - min_x_screen)
        win_h = int(max_y_screen - min_y_screen)

        _debug_log("fitted window positioning",
                  window_bounds=self._window_bounds,
                  content_offset=self._content_offset,
                  retina_scale=scale,
                  bbox_bounds=(int(min_x), int(min_y), int(max_x), int(max_y)),
                  screen_bounds=(int(min_x_screen), int(min_y_screen), int(max_x_screen), int(max_y_screen)),
                  final_geometry=f"{win_w}x{win_h}+{win_x}+{win_y}")

        # Position labels relative to new window origin (in screen coordinates)
        visible_labels = []
        for i, (text, bbox) in enumerate(self._last_regions):
            if not text or not bbox:
                continue

            label = self._get_or_create_inplace_label(i)

            # Convert label position from image to screen coordinates
            rel_x = (bbox["x"] - min_x) / scale
            rel_y = (bbox["y"] - min_y) / scale
            width = bbox["width"] / scale

            label.config(text=text, font=self._inplace_font, wraplength=int(width))
            label.place(x=int(rel_x), y=int(rel_y))
            visible_labels.append(label)

        # Resize and reposition window
        self._inplace_root.deiconify()
        self._inplace_root.wm_minsize(1, 1)
        self._inplace_root.wm_maxsize(win_w + 100, win_h + 100)
        self._inplace_root.geometry(f"{win_w}x{win_h}+{win_x}+{win_y}")
        self._inplace_root.update_idletasks()

        # Debug: add red border around fitted window
        if _debug:
            # Clear old debug borders
            for border in self._debug_borders:
                border.destroy()
            self._debug_borders = []

            border_width = 3
            border_color = "#FF0000"
            top = tk.Frame(self._inplace_root, bg=border_color, height=border_width)
            top.place(x=0, y=0, width=win_w)
            self._debug_borders.append(top)
            bottom = tk.Frame(self._inplace_root, bg=border_color, height=border_width)
            bottom.place(x=0, y=win_h - border_width, width=win_w)
            self._debug_borders.append(bottom)
            left = tk.Frame(self._inplace_root, bg=border_color, width=border_width)
            left.place(x=0, y=0, height=win_h)
            self._debug_borders.append(left)
            right = tk.Frame(self._inplace_root, bg=border_color, width=border_width)
            right.place(x=win_w - border_width, y=0, height=win_h)
            self._debug_borders.append(right)

            self._inplace_root.update_idletasks()
            visible_labels.extend(self._debug_borders)

        # Apply shape mask for click-through (Linux)
        if _update_shape_mask:
            _update_shape_mask(self._inplace_handle, visible_labels)

    def _get_or_create_inplace_label(self, index: int) -> tk.Label:
        """Get an existing inplace label or create a new one."""
        while len(self._inplace_labels) <= index:
            label = tk.Label(
                self._inplace_root,
                text="",
                font=self._inplace_font,
                fg=self.font_color,
                bg="#404040",
                padx=4,
                pady=2,
                justify=tk.LEFT,
                anchor="nw",
            )
            self._inplace_labels.append(label)
        return self._inplace_labels[index]

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    def pause(self):
        """Pause the overlay (hides both windows)."""
        if self._paused:
            return
        self._paused = True
        if self._banner_root:
            self._hide_window(self._banner_root)
        if self._inplace_root:
            self._hide_window(self._inplace_root)

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

    # -------------------------------------------------------------------------
    # Properties
    # -------------------------------------------------------------------------

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
