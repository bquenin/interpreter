"""Linux-specific overlay implementations using Qt.

On Linux:
- Window bounds are in logical pixels (same as macOS)
- Qt handles both X11 and native Wayland
- Dragging requires startSystemMove() on Wayland
"""

from PySide6.QtCore import Qt

from .base import BannerOverlayBase, InplaceOverlayBase


class BannerOverlay(BannerOverlayBase):
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
        """Snap to screen bounds after drag."""
        self._snap_to_current_screen()
        event.accept()


class InplaceOverlay(InplaceOverlayBase):
    """Linux inplace overlay.

    Window bounds are in logical pixels (same as macOS), no conversion needed.
    """

    def position_over_window(self, bounds: dict):
        """Position overlay to cover a window."""
        self.setGeometry(bounds["x"], bounds["y"], bounds["width"], bounds["height"])
