"""Linux-specific overlay implementations using Qt.

On Linux:
- App forces Qt to use X11/XWayland (QT_QPA_PLATFORM=xcb) for reliable stay-on-top
- Window bounds are in logical pixels (same as macOS)
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
