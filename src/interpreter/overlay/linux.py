"""Linux-specific overlay implementations using Qt.

On Linux:
- Window bounds are in logical pixels (same as macOS)
- Qt handles both X11 and native Wayland
- Dragging requires startSystemMove() on Wayland
- Stay-on-top behavior varies by compositor
"""

from PySide6.QtCore import Qt

from .base import BannerOverlayBase, InplaceOverlayBase


class _LinuxOverlayMixin:
    """Mixin for Linux-specific window setup."""

    def _setup_window(self):
        """Configure window flags for overlay behavior on Linux."""
        super()._setup_window()
        # Try multiple hints to help with stay-on-top on various compositors
        # X11DoNotAcceptFocus helps on some X11/XWayland setups
        self.setAttribute(Qt.WidgetAttribute.WA_X11DoNotAcceptFocus, True)


class BannerOverlay(_LinuxOverlayMixin, BannerOverlayBase):
    """Linux banner overlay.

    On Wayland, window dragging requires compositor cooperation via startSystemMove().
    """

    def mousePressEvent(self, event):
        """Start window drag using compositor's interactive move."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.windowHandle().startSystemMove()
            event.accept()

    def mouseMoveEvent(self, event):
        """No-op - compositor handles the move."""
        event.accept()

    def mouseReleaseEvent(self, event):
        """No-op - drag ends when compositor says so."""
        event.accept()


class InplaceOverlay(_LinuxOverlayMixin, InplaceOverlayBase):
    """Linux inplace overlay.

    Window bounds are in logical pixels (same as macOS), no conversion needed.
    """

    def position_over_window(self, bounds: dict):
        """Position overlay to cover a window."""
        self.setGeometry(bounds["x"], bounds["y"], bounds["width"], bounds["height"])
