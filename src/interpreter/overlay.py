"""Unified overlay window for displaying subtitles in banner or inplace mode."""

import platform
import tkinter as tk
from tkinter import font as tkfont
from typing import Optional

# Platform detection
IS_WINDOWS = platform.system() == "Windows"
IS_MACOS = platform.system() == "Darwin"

# Overlay layout constants
DEFAULT_TITLE_BAR_HEIGHT = 32 if IS_WINDOWS else 30  # Title bar height varies by OS
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

        # Bounds tracking
        self._display_bounds: Optional[dict] = None
        self._window_bounds: Optional[dict] = None
        self._retina_scale: float = DEFAULT_RETINA_SCALE
        self._title_bar_height: int = DEFAULT_TITLE_BAR_HEIGHT
        self._last_regions: list[tuple[str, dict]] = []

    def create(self, display_bounds: dict, window_bounds: dict, image_size: tuple[int, int], mode: str = "banner"):
        """Create and configure the overlay window.

        Args:
            display_bounds: Dict with x, y, width, height of the display.
            window_bounds: Dict with x, y, width, height of game window.
            image_size: Tuple of (width, height) of captured image for scale detection.
            mode: Initial mode - "banner" or "inplace".
        """
        self._root = tk.Tk()
        self._root.title("Interpreter Overlay")
        self._display_bounds = display_bounds
        self._window_bounds = window_bounds.copy()
        self._mode = mode

        # Auto-detect Retina scale
        if window_bounds["width"] > 0:
            self._retina_scale = image_size[0] / window_bounds["width"]
        print(f"  Retina scale: {self._retina_scale}x")

        # Configure window properties
        self._root.overrideredirect(True)  # Remove window decorations
        self._root.attributes("-topmost", True)  # Always on top

        # Platform-specific transparency setup
        if IS_WINDOWS:
            # Windows: Use a specific color as transparent
            self._transparent_color = "#010101"  # Near-black, unlikely to be used
            self._root.attributes("-transparentcolor", self._transparent_color)
            self._root.config(bg=self._transparent_color)
            self._label_transparent_bg = self._transparent_color
        else:
            # macOS transparency setup
            self._root.attributes("-transparent", True)
            self._root.config(bg="systemTransparent")
            self._label_transparent_bg = "systemTransparent"

        # Create frame for banner mode
        self._frame = tk.Frame(
            self._root,
            bg=self.background_color,
            padx=20,
            pady=10,
        )

        # Create cached font for all labels (use Arial on Windows, Helvetica on macOS)
        font_family = "Arial" if IS_WINDOWS else "Helvetica"
        self._font = tkfont.Font(family=font_family, size=self.font_size, weight="bold")

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

        # Apply initial mode
        if mode == "banner":
            self._apply_banner_mode()
        else:
            self._apply_inplace_mode()

        # Configure macOS window behavior
        self._setup_macos_overlay()

    def _setup_macos_overlay(self):
        """Configure macOS-specific window behavior."""
        try:
            from AppKit import (
                NSApplication,
                NSWindowCollectionBehaviorCanJoinAllSpaces,
                NSWindowCollectionBehaviorStationary,
            )

            self._root.update_idletasks()
            ns_app = NSApplication.sharedApplication()

            for ns_window in ns_app.windows():
                title = ns_window.title() or ""
                if "Interpreter" in title:
                    self._ns_window = ns_window
                    behavior = (
                        NSWindowCollectionBehaviorCanJoinAllSpaces |
                        NSWindowCollectionBehaviorStationary
                    )
                    ns_window.setCollectionBehavior_(behavior)

                    # Make click-through in inplace mode
                    if self._mode == "inplace":
                        ns_window.setIgnoresMouseEvents_(True)
                    break
        except Exception:
            pass

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

    def update_position(self, window_bounds: dict, display_bounds: dict = None, image_size: tuple[int, int] = None):
        """Update overlay position to follow the game window.

        Args:
            window_bounds: New window bounds dict with x, y, width, height.
            display_bounds: Optional display bounds for banner mode repositioning.
            image_size: Optional tuple of (width, height) to recalculate retina scale.
        """
        # Check for window bounds changes
        window_changed = window_bounds != self._window_bounds
        if window_changed:
            self._window_bounds = window_bounds.copy()

        # Recalculate retina scale if image size provided
        if image_size and window_bounds["width"] > 0:
            self._retina_scale = image_size[0] / window_bounds["width"]

        # Check for display bounds changes
        display_changed = display_bounds and display_bounds != self._display_bounds
        if display_changed:
            self._display_bounds = display_bounds.copy()

        # Apply changes based on mode
        if self._mode == "inplace" and window_changed:
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
        self._root.geometry(f"{width}x{height}+{x}+{y}")

        # Make draggable on macOS
        try:
            if hasattr(self, '_ns_window'):
                self._ns_window.setIgnoresMouseEvents_(False)
        except Exception:
            pass

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
        # Hide banner frame
        self._frame.pack_forget()

        # Position over game window (excluding title bar)
        if self._window_bounds:
            x = self._window_bounds["x"]
            y = self._window_bounds["y"] + self._title_bar_height
            width = self._window_bounds["width"]
            height = self._window_bounds["height"] - self._title_bar_height
        else:
            width = 800
            height = 600
            x = 100
            y = 100

        self._root.wm_minsize(width, height)
        self._root.wm_maxsize(width, height)
        self._root.geometry(f"{width}x{height}+{x}+{y}")

        # Make click-through on macOS
        try:
            if hasattr(self, '_ns_window'):
                self._ns_window.setIgnoresMouseEvents_(True)
        except Exception:
            pass

        self._root.update_idletasks()

        # Re-render any existing regions
        self._render_inplace_regions()

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

        # Render each region
        for i, (text, bbox) in enumerate(self._last_regions):
            if not text or not bbox:
                continue

            # Get or create label
            label = self._get_or_create_inplace_label(i)

            # Convert image coordinates to overlay coordinates
            x = bbox["x"] / self._retina_scale
            y = bbox["y"] / self._retina_scale
            width = bbox["width"] / self._retina_scale

            # Configure and position label
            label.config(text=text, font=self._font, wraplength=int(width))
            label.place(x=x, y=y)

        self._root.update_idletasks()

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
