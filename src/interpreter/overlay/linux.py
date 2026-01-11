"""Linux-specific overlay implementations using Qt.

On Linux:
- Window bounds are in logical pixels (same as macOS)
- Qt handles both X11 and native Wayland
- No platform-specific overrides needed
"""

from .base import BannerOverlayBase, InplaceOverlayBase


class BannerOverlay(BannerOverlayBase):
    """Linux banner overlay - no platform-specific overrides needed."""

    pass


class InplaceOverlay(InplaceOverlayBase):
    """Linux inplace overlay.

    Window bounds are in logical pixels (same as macOS), no conversion needed.
    """

    def position_over_window(self, bounds: dict):
        """Position overlay to cover a window."""
        self.setGeometry(bounds["x"], bounds["y"], bounds["width"], bounds["height"])
