"""Windows-specific overlay implementations.

On Windows:
- Window bounds are in PHYSICAL PIXELS
- Qt uses logical pixels (points) for geometry
- Must divide by scale factor (DPI scaling) when positioning
- Click-through requires Win32 API (WS_EX_TRANSPARENT, WS_EX_LAYERED)
"""

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from .. import log
from .base import BannerOverlayBase, InplaceOverlayBase

logger = log.get_logger()

# Win32 constants
GW_HWNDPREV = 3
HWND_TOP = 0
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010

# Upper bound on how far up the z-order we look for the target window.
# Only topmost windows sit above the overlay, so this is normally a handful.
MAX_ZORDER_WALK = 64


class _WindowsOverlayMixin:
    """Z-order maintenance shared by both Windows overlays.

    Overlays are created with WS_EX_TOPMOST, but Windows keeps all topmost
    windows in one band and moves whichever one was activated last to the
    top of it. Games that make themselves topmost in fullscreen therefore
    cover the overlay as soon as they receive focus, and nothing raises the
    overlay again (issue #255). ensure_above() detects that and re-raises
    the overlay without activating it.
    """

    def ensure_above(self, window_id: int | None) -> None:
        if not window_id or not self.isVisible():
            return
        try:
            user32 = ctypes.windll.user32
            user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
            user32.GetWindow.restype = wintypes.HWND
            hwnd = int(self.winId())
            if not self._is_window_above(user32, hwnd, window_id):
                return
            # HWND_TOP moves a topmost window to the top of the topmost band
            user32.SetWindowPos(hwnd, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
            logger.debug("re-raised overlay above target window", window_id=window_id)
        except Exception as e:
            logger.debug("failed to re-raise overlay", error=str(e))

    @staticmethod
    def _is_window_above(user32, hwnd: int, window_id: int) -> bool:
        """Return True if window_id sits above hwnd in the z-order."""
        current = user32.GetWindow(hwnd, GW_HWNDPREV)
        for _ in range(MAX_ZORDER_WALK):
            if not current:
                return False
            if current == window_id:
                return True
            current = user32.GetWindow(current, GW_HWNDPREV)
        return False


class BannerOverlay(_WindowsOverlayMixin, BannerOverlayBase):
    """Windows banner overlay.

    Only needs z-order maintenance - base class handles everything else.
    """


class InplaceOverlay(_WindowsOverlayMixin, InplaceOverlayBase):
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
