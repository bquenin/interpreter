"""Windows-specific overlay implementations.

On Windows:
- Window bounds are in PHYSICAL PIXELS
- Qt uses logical pixels (points) for geometry
- Must divide by scale factor (DPI scaling) when positioning
- Click-through requires Win32 API (WS_EX_TRANSPARENT, WS_EX_LAYERED)
"""

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from .base import BannerOverlayBase, InplaceOverlayBase


class BannerOverlay(BannerOverlayBase):
    """Windows banner overlay.

    No platform-specific overrides needed - base class handles everything.
    """

    pass


class InplaceOverlay(InplaceOverlayBase):
    """Windows inplace overlay.

    Key differences from macOS:
    - Window bounds are in physical pixels, must convert to logical
    - Click-through requires Win32 extended window styles
    """

    def position_over_window(self, bounds: dict):
        """Position overlay to cover a window.

        On Windows, window bounds are in PHYSICAL PIXELS, but Qt uses
        logical pixels (points). Must divide by the DPI scale factor.

        Args:
            bounds: Dict with x, y, width, height in physical pixels.
        """
        # Find which screen the window is on based on its center point
        center_x = bounds["x"] + bounds["width"] // 2
        center_y = bounds["y"] + bounds["height"] // 2
        screen = QApplication.screenAt(QPoint(center_x, center_y))
        if screen is None:
            screen = QApplication.primaryScreen()

        # Convert from physical pixels to logical pixels (points)
        scale = screen.devicePixelRatio()
        x = int(bounds["x"] / scale)
        y = int(bounds["y"] / scale)
        width = int(bounds["width"] / scale)
        height = int(bounds["height"] / scale)

        self.setGeometry(x, y, width, height)

    def _apply_click_through(self):
        """Apply Windows-specific click-through using Win32 API.

        Qt's WindowTransparentForInput flag doesn't always work on Windows,
        so we also set the WS_EX_TRANSPARENT and WS_EX_LAYERED extended
        window styles directly via Win32 API.
        """
        try:
            import ctypes

            hwnd = int(self.winId())
            GWL_EXSTYLE = -20
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_LAYERED = 0x00080000
            user32 = ctypes.windll.user32
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_TRANSPARENT | WS_EX_LAYERED)
        except Exception:
            # If Win32 API fails, Qt's WindowTransparentForInput should still work
            pass
