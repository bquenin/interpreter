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
    Window repositioning via move() doesn't work - compositor controls placement.
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

    def _resize_to_fit(self, keep_bottom_fixed: bool = True):
        """Resize banner height to fit text - Wayland version.

        On Wayland, we can't use move() to reposition windows, so we skip
        the bottom-edge-fixed behavior. The banner resizes from top-left.
        """
        # Just resize, don't try to move (move() doesn't work on Wayland)
        super()._resize_to_fit(keep_bottom_fixed=False)

    def _snap_to_current_screen(self):
        """No-op on Wayland - can't programmatically reposition windows."""
        # On Wayland, the compositor controls window positioning.
        # After drag ends, the window stays where the user dropped it.
        pass


class InplaceOverlay(InplaceOverlayBase):
    """Linux inplace overlay.

    Window bounds are in logical pixels (same as macOS), no conversion needed.
    """

    def position_over_window(self, bounds: dict):
        """Position overlay to cover a window."""
        self.setGeometry(bounds["x"], bounds["y"], bounds["width"], bounds["height"])
