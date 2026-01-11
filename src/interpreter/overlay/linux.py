"""Linux-specific overlay implementations using Qt.

This module provides Qt-based overlays for Linux, supporting both X11 and Wayland.

On Linux:
- Window bounds are typically in logical pixels (like macOS)
- Click-through uses Qt's WindowTransparentForInput flag
- Stay-on-top behavior may vary by compositor/window manager

Known limitations to evaluate:
- Stay-on-top over fullscreen applications (varies by compositor)
- Click-through transparency on X11 vs Wayland
- Window positioning with different compositors
"""

from PySide6.QtCore import Qt

from .base import BannerOverlayBase, InplaceOverlayBase


class BannerOverlay(BannerOverlayBase):
    """Linux banner overlay using Qt.

    On Wayland, window dragging requires compositor cooperation via startSystemMove().
    """

    def _setup_window(self):
        """Configure window flags for overlay behavior."""
        super()._setup_window()
        # On some Linux compositors, this hint helps with layering
        self.setAttribute(Qt.WidgetAttribute.WA_X11NetWmWindowTypeNotification, True)

    def mousePressEvent(self, event):
        """Start window drag using compositor's interactive move.

        On Wayland, applications cannot arbitrarily reposition windows.
        We must ask the compositor to perform the move via startSystemMove().
        """
        if event.button() == Qt.MouseButton.LeftButton:
            # Use system move - works on both X11 and Wayland
            self.windowHandle().startSystemMove()
            event.accept()

    def mouseMoveEvent(self, event):
        """No-op on Linux - compositor handles the move."""
        event.accept()

    def mouseReleaseEvent(self, event):
        """Handle end of drag - snap to screen bounds."""
        self._snap_to_current_screen()
        event.accept()


class InplaceOverlay(InplaceOverlayBase):
    """Linux inplace overlay using Qt.

    On Linux, window bounds are typically in logical pixels (same as macOS),
    so no coordinate conversion is needed.
    """

    def _setup_window(self):
        """Configure window flags for overlay behavior."""
        super()._setup_window()
        # Additional hint for X11/Wayland compositors
        self.setAttribute(Qt.WidgetAttribute.WA_X11NetWmWindowTypeNotification, True)

    def position_over_window(self, bounds: dict):
        """Position overlay to cover a window.

        On Linux, window bounds are typically in logical pixels (points),
        similar to macOS. No conversion needed.

        Args:
            bounds: Dict with x, y, width, height in logical pixels.
        """
        self.setGeometry(bounds["x"], bounds["y"], bounds["width"], bounds["height"])
