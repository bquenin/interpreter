"""Unified overlay window for displaying subtitles in banner or inplace mode."""

import platform
import time
import tkinter as tk
from tkinter import font as tkfont
from typing import Optional

from .. import log

# Debug flag - set via Overlay.set_debug()
_debug = False
_logger = log.get_logger()

def _debug_log(msg: str, **kwargs):
    """Log debug messages if debug mode is enabled."""
    if _debug:
        _logger.debug(msg, **kwargs)

# Import platform-specific implementation
_system = platform.system()

# Platform-specific shape mask functions (Linux only)
_update_shape_mask = None
_reset_shape_mask = None

if _system == "Darwin":
    from .macos import TITLE_BAR_HEIGHT, FONT_FAMILY, setup_transparency, setup_window, set_click_through
elif _system == "Windows":
    from .windows import TITLE_BAR_HEIGHT, FONT_FAMILY, setup_transparency, setup_window, set_click_through
elif _system == "Linux":
    from .linux import TITLE_BAR_HEIGHT, FONT_FAMILY, setup_transparency, setup_window, set_click_through
    from .linux import update_shape_mask as _update_shape_mask, reset_shape_mask as _reset_shape_mask
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

    Supports two modes:
    - banner: Fixed position at bottom of screen, opaque background, centered text
    - inplace: Follows game window, transparent background, text at OCR bbox positions
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

        self._root: Optional[tk.Tk] = None
        self._frame: Optional[tk.Frame] = None
        self._banner_label: Optional[tk.Label] = None
        self._inplace_labels: list[tk.Label] = []
        self._font: Optional[tkfont.Font] = None
        self._current_text: str = ""
        self._paused: bool = False  # When paused, overlay shows nothing
        self._mode: str = "banner"  # "banner" or "inplace"

        # Platform-specific state
        self._window_handle = None  # Platform window handle (e.g., NSWindow on macOS)
        self._transparent_color: str = ""
        self._label_transparent_bg: str = ""

        # Bounds tracking
        self._display_bounds: Optional[dict] = None
        self._window_bounds: Optional[dict] = None
        self._image_size: tuple[int, int] = (0, 0)  # Actual captured image size
        self._retina_scale: float = DEFAULT_RETINA_SCALE
        self._title_bar_height: int = TITLE_BAR_HEIGHT
        self._last_regions: list[tuple[str, dict]] = []

    @staticmethod
    def set_debug(enabled: bool):
        """Enable or disable debug output."""
        global _debug
        _debug = enabled

    def create(self, display_bounds: dict, window_bounds: dict, image_size: tuple[int, int], mode: str = "banner", content_offset: tuple[int, int] = (0, 0)):
        """Create and configure the overlay window.

        Args:
            display_bounds: Dict with x, y, width, height of the display.
            window_bounds: Dict with x, y, width, height of game window.
            image_size: Tuple of (width, height) of captured image for scale detection.
            mode: Initial mode - "banner" or "inplace".
            content_offset: Tuple of (x, y) offset from window bounds to content area.
        """
        _debug_log("overlay create", mode=mode, platform=_system, content_offset=content_offset)

        self._root = tk.Tk()
        self._root.title("Interpreter Overlay")

        self._display_bounds = display_bounds
        self._window_bounds = window_bounds.copy()
        self._image_size = image_size
        self._content_offset = content_offset  # Offset from window bounds to content
        self._mode = mode

        # Auto-detect Retina scale (for coordinate conversion)
        if window_bounds["width"] > 0:
            self._retina_scale = image_size[0] / window_bounds["width"]

        # Configure window properties
        self._root.overrideredirect(True)  # Remove window decorations
        self._root.attributes("-topmost", True)  # Always on top

        # Platform-specific transparency setup
        self._transparent_color, self._label_transparent_bg = setup_transparency(self._root)

        # Create frame for banner mode
        self._frame = tk.Frame(
            self._root,
            bg=self.background_color,
            padx=20,
            pady=10,
        )

        # Create cached font for all labels
        self._font = tkfont.Font(family=FONT_FAMILY, size=self.font_size, weight="bold")

        # Create label for banner mode
        self._banner_label = tk.Label(
            self._frame,
            text="",
            font=self._font,
            fg=self.font_color,
            bg=self.background_color,
            justify=tk.CENTER,
        )
        self._banner_label.pack(expand=True)

        # Allow dragging in banner mode
        self._frame.bind("<Button-1>", self._start_drag)
        self._frame.bind("<B1-Motion>", self._on_drag)
        self._banner_label.bind("<Button-1>", self._start_drag)
        self._banner_label.bind("<B1-Motion>", self._on_drag)

        # Platform-specific window setup (must happen before applying mode for shape masks)
        self._window_handle = setup_window(self._root, mode)

        # Apply initial mode
        if mode == "banner":
            self._apply_banner_mode()
        else:
            self._apply_inplace_mode()

        self._root.update_idletasks()

        # On Linux, delay initial shape mask to ensure window is fully mapped
        if _system == "Linux" and mode == "inplace" and _update_shape_mask:
            self._root.after(100, lambda: _update_shape_mask(self._window_handle, []))

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
            self._apply_banner_mode()
        else:
            self._apply_inplace_mode()

    def adjust_font_size(self, delta: int):
        """Adjust the font size by delta pixels.

        Args:
            delta: Amount to change font size (positive or negative).
        """
        new_size = max(MIN_FONT_SIZE, min(MAX_FONT_SIZE, self.font_size + delta))
        if new_size == self.font_size:
            return
        self.font_size = new_size

        # Update cached font (automatically updates all labels using it)
        if self._font:
            self._font.configure(size=self.font_size)

        if self._root:
            self._root.update_idletasks()

    def update_position(self, window_bounds: dict, display_bounds: dict = None, image_size: tuple[int, int] = None, content_offset: tuple[int, int] = None):
        """Update overlay position to follow the game window.

        Args:
            window_bounds: New window bounds dict with x, y, width, height.
            display_bounds: Optional display bounds for banner mode repositioning.
            image_size: Optional tuple of (width, height) to recalculate retina scale.
            content_offset: Optional tuple of (x, y) offset for content area within window.
        """
        # Check for window bounds changes
        window_changed = window_bounds != self._window_bounds
        if window_changed:
            self._window_bounds = window_bounds.copy()

        # Check for content offset changes (e.g., fullscreen transition)
        if content_offset is not None and content_offset != self._content_offset:
            _debug_log("content offset changed", old=self._content_offset, new=content_offset)
            self._content_offset = content_offset

        # Check for image size changes (e.g., fullscreen transition)
        image_changed = image_size and image_size != self._image_size
        if image_changed:
            _debug_log("image size changed", old_size=self._image_size, new_size=image_size)
            self._image_size = image_size

        # Recalculate retina scale if image size provided
        if image_size and window_bounds["width"] > 0:
            self._retina_scale = image_size[0] / window_bounds["width"]

        # Check for display bounds changes
        display_changed = display_bounds and display_bounds != self._display_bounds
        if display_changed:
            self._display_bounds = display_bounds.copy()

        # Apply changes based on mode
        if self._mode == "inplace" and (window_changed or image_changed):
            self._apply_inplace_mode()
        elif self._mode == "banner" and display_changed:
            self._apply_banner_mode()

    # -------------------------------------------------------------------------
    # Banner Mode
    # -------------------------------------------------------------------------

    def _apply_banner_mode(self):
        """Configure overlay for banner mode."""
        # Hide inplace labels
        for label in self._inplace_labels:
            label.place_forget()

        # Reset shape mask on Linux (show full window)
        if _reset_shape_mask:
            _reset_shape_mask(self._window_handle)

        # Show banner frame
        self._frame.pack(expand=True, fill=tk.BOTH)

        # Position at bottom of display
        if self._display_bounds:
            width = self._display_bounds["width"]
            height = BANNER_HEIGHT
            x = self._display_bounds["x"]
            y = self._display_bounds["y"] + self._display_bounds["height"] - height - BANNER_BOTTOM_MARGIN
        else:
            width = self._root.winfo_screenwidth()
            height = BANNER_HEIGHT
            x = 0
            y = self._root.winfo_screenheight() - height - BANNER_BOTTOM_MARGIN

        # Reset size constraints (inplace mode sets these)
        screen_w = self._root.winfo_screenwidth()
        screen_h = self._root.winfo_screenheight()
        self._root.wm_minsize(1, 1)
        self._root.wm_maxsize(screen_w, screen_h)

        self._banner_label.config(wraplength=width - 60)
        geometry_str = f"{width}x{height}+{x}+{y}"
        self._root.geometry(geometry_str)

        # Make draggable (disable click-through)
        set_click_through(self._window_handle, False)

        self._root.update_idletasks()

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
            self._root.update_idletasks()
            required_height = self._banner_label.winfo_reqheight() + 30
            current_width = self._root.winfo_width()
            current_x = self._root.winfo_x()
            current_height = self._root.winfo_height()
            current_y = self._root.winfo_y()

            # Adjust position to keep bottom edge in place
            current_bottom = current_y + current_height
            new_y = current_bottom - required_height

            self._root.geometry(f"{current_width}x{required_height}+{current_x}+{new_y}")

    def _start_drag(self, event):
        """Start dragging the window (banner mode only)."""
        if self._mode == "banner":
            self._drag_start_x = event.x
            self._drag_start_y = event.y

    def _on_drag(self, event):
        """Handle window dragging (banner mode only)."""
        if self._mode == "banner":
            x = self._root.winfo_x() + event.x - self._drag_start_x
            y = self._root.winfo_y() + event.y - self._drag_start_y
            self._root.geometry(f"+{x}+{y}")

    # -------------------------------------------------------------------------
    # Inplace Mode
    # -------------------------------------------------------------------------

    def _apply_inplace_mode(self):
        """Configure overlay for inplace mode."""
        start_time = time.time()
        _debug_log("inplace mode START")

        # Hide banner frame
        self._frame.pack_forget()

        # On Linux, use fitted window approach - skip fullscreen overlay setup
        if _system == "Linux":
            set_click_through(self._window_handle, True)
            self._render_inplace_regions()
            _debug_log("inplace mode COMPLETE (fitted)", total_ms=int((time.time() - start_time) * 1000))
            return

        # macOS/Windows: Position fullscreen overlay over game window content area
        if self._window_bounds:
            x_offset = self._content_offset[0]
            y_offset = self._content_offset[1]

            if y_offset == 0 and self._window_bounds["width"] > 0:
                width = self._window_bounds["width"]
                height = self._window_bounds["height"]
            elif self._image_size[0] > 0:
                width = self._image_size[0]
                height = self._image_size[1]
            else:
                width = self._window_bounds["width"]
                height = self._window_bounds["height"]

            x = self._window_bounds["x"] + x_offset
            y = self._window_bounds["y"] + y_offset

            _debug_log("inplace positioning",
                      window_bounds=self._window_bounds,
                      image_size=self._image_size,
                      content_offset=self._content_offset,
                      final_pos=(x, y),
                      final_size=(width, height))
        else:
            width = 800
            height = 600
            x = 100
            y = 100

        t1 = time.time()
        self._root.wm_minsize(width, height)
        self._root.wm_maxsize(width, height)
        self._root.geometry(f"{width}x{height}+{x}+{y}")
        _debug_log("geometry set", elapsed_ms=int((time.time() - t1) * 1000))

        # Debug: add visible border to see overlay position
        self._debug_borders = []
        if _debug:
            border_width = 3
            border_color = "#FF0000"
            top = tk.Frame(self._root, bg=border_color, height=border_width)
            top.place(x=0, y=0, width=width)
            self._debug_borders.append(top)
            bottom = tk.Frame(self._root, bg=border_color, height=border_width)
            bottom.place(x=0, y=height-border_width, width=width)
            self._debug_borders.append(bottom)
            left = tk.Frame(self._root, bg=border_color, width=border_width)
            left.place(x=0, y=0, height=height)
            self._debug_borders.append(left)
            right = tk.Frame(self._root, bg=border_color, width=border_width)
            right.place(x=width-border_width, y=0, height=height)
            self._debug_borders.append(right)

        set_click_through(self._window_handle, True)

        t2 = time.time()
        self._root.update_idletasks()
        _debug_log("update_idletasks done", elapsed_ms=int((time.time() - t2) * 1000))

        self._render_inplace_regions()

        _debug_log("inplace mode COMPLETE", total_ms=int((time.time() - start_time) * 1000))

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
        """Render all text regions at their bbox positions."""
        if self._root is None:
            return

        # Hide all existing labels first
        for label in self._inplace_labels:
            label.place_forget()

        # Track which labels are visible for shape mask
        visible_labels = []

        # On Linux, use fitted window approach instead of shape masks
        # Shape masks don't work reliably with Mutter/XWayland over fullscreen
        if _system == "Linux":
            self._render_inplace_fitted()
            return

        # Render each region
        for i, (text, bbox) in enumerate(self._last_regions):
            if not text or not bbox:
                continue

            # Get or create label
            label = self._get_or_create_inplace_label(i)

            # Use raw image coordinates - overlay now matches image size exactly
            x = bbox["x"]
            y = bbox["y"]
            width = bbox["width"]

            # Configure and position label
            label.config(text=text, font=self._font, wraplength=int(width))
            label.place(x=x, y=y)
            visible_labels.append(label)

        self._root.update_idletasks()

        # Apply shape mask on Linux for transparency
        # Include debug borders if present
        all_visible = visible_labels.copy()
        if hasattr(self, '_debug_borders'):
            all_visible.extend(self._debug_borders)

        # Always call update_shape_mask - with empty list it will hide the window
        if _update_shape_mask:
            _update_shape_mask(self._window_handle, all_visible)

    def _render_inplace_fitted(self):
        """Render regions using a fitted window (Linux-specific).

        Instead of a fullscreen overlay with shape masks, resize the window
        to just fit the label bounding boxes. This works better with
        Mutter/XWayland which doesn't respect shape masks over fullscreen.
        """
        if not self._last_regions:
            # No regions - hide window
            self._root.withdraw()
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
            w, h = bbox["width"], bbox.get("height", 80)  # Estimate height
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x + w)
            max_y = max(max_y, y + h)

        if min_x == float('inf'):
            self._root.withdraw()
            return

        # Add padding
        padding = 10
        min_x = max(0, min_x - padding)
        min_y = max(0, min_y - padding)
        max_x += padding
        max_y += padding

        # Calculate window position (relative to game window)
        win_x = self._window_bounds["x"] + self._content_offset[0] + int(min_x)
        win_y = self._window_bounds["y"] + self._content_offset[1] + int(min_y)
        win_w = int(max_x - min_x)
        win_h = int(max_y - min_y)

        _debug_log("fitted window positioning",
                  window_bounds=self._window_bounds,
                  content_offset=self._content_offset,
                  bbox_bounds=(int(min_x), int(min_y), int(max_x), int(max_y)),
                  final_geometry=f"{win_w}x{win_h}+{win_x}+{win_y}")

        # Position labels relative to new window origin
        visible_labels = []
        for i, (text, bbox) in enumerate(self._last_regions):
            if not text or not bbox:
                continue

            label = self._get_or_create_inplace_label(i)

            # Position relative to the fitted window
            rel_x = bbox["x"] - min_x
            rel_y = bbox["y"] - min_y
            width = bbox["width"]

            label.config(text=text, font=self._font, wraplength=int(width))
            label.place(x=rel_x, y=rel_y)
            visible_labels.append(label)

        # Resize and reposition window
        self._root.deiconify()
        self._root.wm_minsize(1, 1)
        self._root.wm_maxsize(win_w + 100, win_h + 100)
        self._root.geometry(f"{win_w}x{win_h}+{win_x}+{win_y}")
        self._root.update_idletasks()

        # Debug: add red border around fitted window
        if _debug:
            # Clear old debug borders
            if hasattr(self, '_debug_borders'):
                for border in self._debug_borders:
                    border.destroy()
            self._debug_borders = []

            border_width = 3
            border_color = "#FF0000"
            # Top
            top = tk.Frame(self._root, bg=border_color, height=border_width)
            top.place(x=0, y=0, width=win_w)
            self._debug_borders.append(top)
            # Bottom
            bottom = tk.Frame(self._root, bg=border_color, height=border_width)
            bottom.place(x=0, y=win_h - border_width, width=win_w)
            self._debug_borders.append(bottom)
            # Left
            left = tk.Frame(self._root, bg=border_color, width=border_width)
            left.place(x=0, y=0, height=win_h)
            self._debug_borders.append(left)
            # Right
            right = tk.Frame(self._root, bg=border_color, width=border_width)
            right.place(x=win_w - border_width, y=0, height=win_h)
            self._debug_borders.append(right)

            self._root.update_idletasks()  # Compute border geometry
            visible_labels.extend(self._debug_borders)

        # Now apply shape mask - should work on smaller window
        if _update_shape_mask:
            _update_shape_mask(self._window_handle, visible_labels)

    def _get_or_create_inplace_label(self, index: int) -> tk.Label:
        """Get an existing inplace label or create a new one."""
        while len(self._inplace_labels) <= index:
            label = tk.Label(
                self._root,
                text="",
                font=self._font,
                fg=self.font_color,
                bg="#404040",  # Gray background for readability
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
        """Pause the overlay (clears content but keeps window)."""
        if self._paused:
            return
        self._paused = True
        # Clear all content
        if self._banner_label:
            self._banner_label.config(text="")
        if self._frame:
            self._frame.pack_forget()
        for label in self._inplace_labels:
            label.place_forget()
        # Update shape mask to hide everything (Linux)
        if _system == "Linux" and self._window_handle:
            _update_shape_mask(self._window_handle, [])

    def resume(self):
        """Resume the overlay (restores content)."""
        if not self._paused:
            return
        self._paused = False
        # Restore content
        if self._mode == "banner":
            if self._frame:
                self._frame.pack(expand=True, fill=tk.BOTH)
            if self._banner_label:
                self._banner_label.pack(expand=True)
                if self._current_text:
                    self._banner_label.config(text=self._current_text)
            self._root.update_idletasks()
        else:
            # Inplace mode - re-render regions
            self._render_inplace_regions()

    def quit(self):
        """Close the overlay and quit the application."""
        if self._root:
            self._root.quit()
            self._root.destroy()

    def update(self):
        """Process pending Tkinter events (call this in main loop)."""
        if self._root:
            self._root.update()

    # -------------------------------------------------------------------------
    # Properties
    # -------------------------------------------------------------------------

    @property
    def paused(self) -> bool:
        """Check if overlay is paused."""
        return self._paused

    @property
    def is_running(self) -> bool:
        """Check if the overlay window is still running."""
        try:
            if self._root:
                self._root.winfo_exists()
                return True
        except tk.TclError:
            pass
        return False

    @property
    def mode(self) -> str:
        """Get the current mode."""
        return self._mode
