"""macOS-specific overlay implementations.

On macOS:
- CGWindowBounds returns coordinates in POINTS (logical pixels)
- Qt also uses points for geometry
- No conversion needed for window positioning
- Click-through works via Qt.WindowTransparentForInput flag
"""

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QPoint

from .overlay_base import BannerOverlayBase, InplaceOverlayBase


class BannerOverlay(BannerOverlayBase):
    """macOS banner overlay.

    No platform-specific overrides needed - base class handles everything.
    """

    def _setup_window(self):
        """Configure window flags for overlay behavior."""
        super()._setup_window()
        # macOS: ensure window stays on top across Spaces
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)


class InplaceOverlay(InplaceOverlayBase):
    """macOS inplace overlay.

    Key difference from Windows:
    - Window bounds from CGWindowBounds are already in points (logical pixels)
    - No coordinate conversion needed for positioning
    """

    def _setup_window(self):
        """Configure window flags for overlay behavior."""
        super()._setup_window()
        # macOS: ensure window stays on top across Spaces
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)

    def position_over_window(self, bounds: dict):
        """Position overlay to cover a window.

        On macOS, CGWindowBounds returns coordinates in POINTS (logical pixels),
        which is the same coordinate system Qt uses. No conversion needed.

        Args:
            bounds: Dict with x, y, width, height in points from CGWindowBounds.
        """
        # Use bounds directly - already in points
        x = bounds["x"]
        y = bounds["y"]
        width = bounds["width"]
        height = bounds["height"]

        self.setGeometry(x, y, width, height)
