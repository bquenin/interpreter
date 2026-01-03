"""Linux Qt-based overlay fallback.

Used when tkinter is not available (e.g., in uv-managed Python environments).
Qt overlays on Linux may have issues with:
- Stay-on-top behavior over fullscreen apps
- Click-through transparency on some compositors

If you experience issues, install python3-tk via your package manager.
"""

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from .overlay_base import BannerOverlayBase, InplaceOverlayBase


class BannerOverlay(BannerOverlayBase):
    """Linux Qt banner overlay."""

    def _setup_window(self):
        """Configure window flags for overlay behavior."""
        super()._setup_window()
        # Try to set X11 bypass for better overlay behavior
        self.setWindowFlag(Qt.WindowType.X11BypassWindowManagerHint, False)


class InplaceOverlay(InplaceOverlayBase):
    """Linux Qt inplace overlay."""

    def _setup_window(self):
        """Configure window flags for overlay behavior."""
        super()._setup_window()
        # Try to set X11 bypass for better overlay behavior
        self.setWindowFlag(Qt.WindowType.X11BypassWindowManagerHint, False)

    def position_over_window(self, bounds: dict):
        """Position overlay to cover a window.

        On Linux, window bounds are in pixels. Qt uses logical pixels,
        so we may need to account for scaling on HiDPI displays.

        Args:
            bounds: Dict with x, y, width, height in pixels.
        """
        scale = self._get_scale_factor()

        # Convert from physical pixels to logical pixels if needed
        x = int(bounds["x"] / scale)
        y = int(bounds["y"] / scale)
        width = int(bounds["width"] / scale)
        height = int(bounds["height"] / scale)

        self.setGeometry(x, y, width, height)
