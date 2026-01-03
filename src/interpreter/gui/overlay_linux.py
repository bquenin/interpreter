"""Linux overlay implementation using Tkinter with X11 shape extension.

This module provides BannerOverlay and InplaceOverlay classes that are compatible
with the Qt-based overlays in overlay.py, but use Tkinter internally for proper
window behavior on Linux (stay-on-top, positioning, click-through).

The Tkinter event loop is pumped by a Qt timer to coexist with the Qt main window.
"""

from typing import Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from .tk_overlay import Overlay as TkOverlay


# Shared Tkinter overlay instance (both banner and inplace use the same Tk windows)
_tk_overlay: Optional[TkOverlay] = None
_tk_timer: Optional[QTimer] = None
_initialized = False


def _get_or_create_overlay(font_size: int, font_color: str, background_color: str) -> TkOverlay:
    """Get or create the shared Tkinter overlay instance."""
    global _tk_overlay, _tk_timer, _initialized

    if _tk_overlay is None:
        _tk_overlay = TkOverlay(
            font_size=font_size,
            font_color=font_color,
            background_color=background_color,
        )

    if not _initialized:
        # Get display bounds from Qt (primary screen)
        screen = QApplication.primaryScreen()
        screen_geom = screen.geometry()
        display_bounds = {
            "x": screen_geom.x(),
            "y": screen_geom.y(),
            "width": screen_geom.width(),
            "height": screen_geom.height(),
        }

        # Create the Tkinter windows (starts in banner mode, hidden)
        # Using display bounds as initial window bounds
        _tk_overlay.create(
            display_bounds=display_bounds,
            window_bounds=display_bounds.copy(),
            image_size=(display_bounds["width"], display_bounds["height"]),
            mode="banner",
        )

        # Hide both windows initially
        _tk_overlay.pause()

        # Set up Qt timer to pump Tkinter events
        _tk_timer = QTimer()
        _tk_timer.timeout.connect(_pump_tk_events)
        _tk_timer.start(16)  # ~60fps for smooth updates

        _initialized = True

    return _tk_overlay


def _pump_tk_events():
    """Pump Tkinter events from Qt event loop."""
    global _tk_overlay
    if _tk_overlay and _tk_overlay.is_running:
        try:
            _tk_overlay.update()
        except Exception:
            pass  # Ignore Tk errors during shutdown


class BannerOverlay:
    """Banner-style overlay at bottom of screen.

    A draggable subtitle bar that displays translated text.
    This is a wrapper around the Tkinter-based overlay for Linux.
    """

    def __init__(
        self,
        font_size: int = 24,
        font_color: str = "#FFFFFF",
        background_color: str = "#404040",
    ):
        self._font_size = font_size
        self._font_color = font_color
        self._background_color = background_color
        self._visible = False

        # Initialize shared overlay
        _get_or_create_overlay(font_size, font_color, background_color)

    def set_text(self, text: str):
        """Update the displayed text."""
        if _tk_overlay:
            _tk_overlay.update_text(text)

    def set_font_size(self, size: int):
        """Update the font size."""
        self._font_size = size
        if _tk_overlay:
            # Calculate delta from current size
            delta = size - _tk_overlay.font_size
            if delta != 0:
                _tk_overlay.adjust_font_size(delta)

    def set_colors(self, font_color: str, background_color: str):
        """Update the colors."""
        self._font_color = font_color
        self._background_color = background_color
        # Tkinter overlay doesn't support dynamic color changes,
        # colors are set at creation time

    @property
    def font_size(self) -> int:
        return self._font_size

    def show(self):
        """Show the banner overlay."""
        if _tk_overlay and not self._visible:
            _tk_overlay.set_mode("banner")
            _tk_overlay.resume()
            self._visible = True

    def hide(self):
        """Hide the banner overlay."""
        if _tk_overlay and self._visible:
            _tk_overlay.pause()
            self._visible = False

    def close(self):
        """Close the overlay."""
        global _tk_overlay, _tk_timer, _initialized
        if _tk_overlay:
            _tk_overlay.quit()
            _tk_overlay = None
        if _tk_timer:
            _tk_timer.stop()
            _tk_timer = None
        _initialized = False


class InplaceOverlay:
    """Transparent overlay for inplace text display.

    A click-through overlay that positions translated text
    directly over the original game text.
    This is a wrapper around the Tkinter-based overlay for Linux.
    """

    def __init__(
        self,
        font_size: int = 18,
        font_color: str = "#FFFFFF",
        background_color: str = "#000000",
    ):
        self._font_size = font_size
        self._font_color = font_color
        self._background_color = background_color
        self._visible = False
        self._last_bounds: dict = {}
        self._content_offset: tuple[int, int] = (0, 0)

        # Initialize shared overlay
        _get_or_create_overlay(font_size, font_color, background_color)

    def set_regions(self, regions: list[tuple[str, dict]], content_offset: tuple[int, int] = (0, 0)):
        """Update text regions.

        Args:
            regions: List of (text, bbox) tuples where bbox is a dict with x, y, width, height
            content_offset: Tuple of (x, y) offset in pixels for content area within window
        """
        if _tk_overlay:
            # Check if content offset changed
            offset_changed = content_offset != self._content_offset
            self._content_offset = content_offset

            # If offset changed and we have bounds, update position
            if offset_changed and self._last_bounds:
                self._update_position_with_offset(self._last_bounds)

            _tk_overlay.update_regions(regions)

    def _update_position_with_offset(self, bounds: dict):
        """Internal method to update position with current content offset."""
        screen = QApplication.primaryScreen()
        scale = screen.devicePixelRatio()

        # Pass window dimensions as image_size so retina_scale = 1.0 on non-HiDPI
        # The CLI overlay calculates retina_scale = image_size[0] / bounds["width"]
        # We want scale = 1.0 for non-HiDPI, so image_size should match bounds
        # The content_offset handles the decoration offset separately
        image_size = (int(bounds["width"] * scale), int(bounds["height"] * scale))

        _tk_overlay.update_position(
            bounds,
            image_size=image_size,
            content_offset=self._content_offset
        )

    def position_over_window(self, bounds: dict):
        """Position overlay to cover a window.

        Args:
            bounds: Dict with x, y, width, height (in screen/logical pixels)
        """
        if _tk_overlay:
            self._last_bounds = bounds.copy()
            self._update_position_with_offset(bounds)

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
        # Tkinter overlay doesn't support dynamic color changes

    @property
    def font_size(self) -> int:
        return self._font_size

    def show(self):
        """Show the inplace overlay."""
        if _tk_overlay and not self._visible:
            _tk_overlay.set_mode("inplace")
            _tk_overlay.resume()
            self._visible = True

    def hide(self):
        """Hide the inplace overlay."""
        if _tk_overlay and self._visible:
            _tk_overlay.pause()
            self._visible = False

    def close(self):
        """Close the overlay."""
        global _tk_overlay, _tk_timer, _initialized
        if _tk_overlay:
            _tk_overlay.quit()
            _tk_overlay = None
        if _tk_timer:
            _tk_timer.stop()
            _tk_timer = None
        _initialized = False
