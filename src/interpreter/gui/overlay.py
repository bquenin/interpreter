"""PySide6 overlay windows for banner and inplace modes."""

import platform
from typing import Optional

from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QApplication
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QFont

_system = platform.system()


class BannerOverlay(QWidget):
    """Banner-style overlay at bottom of screen.

    A draggable subtitle bar that displays translated text.
    """

    def __init__(
        self,
        font_size: int = 24,
        font_color: str = "#FFFFFF",
        background_color: str = "#404040",
    ):
        super().__init__()
        self._drag_pos: Optional[QPoint] = None
        self._font_size = font_size
        self._font_color = font_color
        self._background_color = background_color
        self._setup_window()
        self._setup_ui()

    def _setup_window(self):
        """Configure window flags for overlay behavior."""
        flags = (
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool  # Hides from taskbar
        )

        # Linux/X11: Use BypassWindowManagerHint for proper positioning
        # Wayland doesn't support arbitrary positioning, so this helps on X11
        if _system == "Linux":
            flags |= Qt.WindowType.X11BypassWindowManagerHint
        else:
            flags |= Qt.WindowType.WindowDoesNotAcceptFocus

        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        # macOS: ensure window stays on top
        if _system == "Darwin":
            self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)

        self.setStyleSheet(f"background-color: {self._background_color};")

        # Use full screen width
        screen = QApplication.primaryScreen().geometry()
        self.resize(screen.width(), 100)
        self._move_to_bottom()

    def _setup_ui(self):
        """Set up the text label."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 10, 20, 10)

        self._label = QLabel("")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setWordWrap(True)
        self._update_label_style()
        layout.addWidget(self._label)

    def _update_label_style(self):
        """Update label font and color."""
        self._label.setFont(QFont("Arial", self._font_size, QFont.Weight.Bold))
        self._label.setStyleSheet(f"color: {self._font_color}; background: transparent;")

    def _move_to_bottom(self):
        """Position at bottom of screen."""
        screen = QApplication.primaryScreen().geometry()
        x = 0  # Full width, start at left edge
        y = screen.height() - self.height() - 50
        self.move(x, y)

    def set_text(self, text: str):
        """Update the displayed text."""
        self._label.setText(text)

    def set_font_size(self, size: int):
        """Update the font size."""
        self._font_size = size
        self._update_label_style()

    def set_colors(self, font_color: str, background_color: str):
        """Update the colors."""
        self._font_color = font_color
        self._background_color = background_color
        self.setStyleSheet(f"background-color: {self._background_color};")
        self._update_label_style()

    @property
    def font_size(self) -> int:
        return self._font_size

    def showEvent(self, event):
        """Handle show event - reposition on Linux/Wayland."""
        super().showEvent(event)
        # On Wayland, repositioning after show may help
        if _system == "Linux":
            self._move_to_bottom()

    # Dragging support
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # On Wayland, use system move (compositor handles it)
            # On X11/macOS/Windows, use manual tracking
            if _system == "Linux":
                self.windowHandle().startSystemMove()
            else:
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None


class InplaceOverlay(QWidget):
    """Transparent overlay for inplace text display.

    A click-through overlay that positions translated text
    directly over the original game text.
    """

    def __init__(
        self,
        font_size: int = 18,
        font_color: str = "#FFFFFF",
        background_color: str = "#000000",
    ):
        super().__init__()
        self._labels: list[QLabel] = []
        self._font_size = font_size
        self._font_color = font_color
        self._background_color = background_color
        # For Linux: stores target window position and monitor offset
        self._window_bounds: dict = {}
        self._monitor_offset: tuple[int, int] = (0, 0)
        self._setup_window()

    def _setup_window(self):
        """Configure window flags for transparent, click-through overlay."""
        flags = (
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )

        # Click-through on all platforms
        flags |= Qt.WindowType.WindowTransparentForInput

        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        # macOS: ensure window stays on top
        if _system == "Darwin":
            self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)

        # Full screen size by default
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)

    def set_regions(self, regions: list[tuple[str, dict]], content_offset: tuple[int, int] = (0, 0)):
        """Update text regions.

        Args:
            regions: List of (text, bbox) tuples where bbox is a dict with x, y, width, height
            content_offset: Tuple of (x, y) offset in pixels for content area within window
        """
        # Get scale factor from the screen this overlay is on (for multi-monitor support)
        screen = self.screen()
        if screen is None:
            screen = QApplication.primaryScreen()
        scale = screen.devicePixelRatio()

        # Convert content offset from pixels to points
        content_offset_x = int(content_offset[0] / scale)
        content_offset_y = int(content_offset[1] / scale)

        # Remove old labels
        for label in self._labels:
            label.deleteLater()
        self._labels.clear()

        # On Linux, calculate window offset relative to monitor
        # (overlay covers full monitor, labels need absolute positioning)
        if _system == "Linux" and self._window_bounds:
            window_offset_x = self._window_bounds.get("x", 0) - self._monitor_offset[0]
            window_offset_y = self._window_bounds.get("y", 0) - self._monitor_offset[1]
        else:
            window_offset_x = 0
            window_offset_y = 0

        # Create new labels
        for text, bbox in regions:
            if not bbox:
                continue
            label = QLabel(text, self)
            label.setFont(QFont("Arial", self._font_size, QFont.Weight.Bold))
            # Convert hex background color to rgba with transparency
            bg_color = self._background_color.lstrip('#')
            r, g, b = int(bg_color[0:2], 16), int(bg_color[2:4], 16), int(bg_color[4:6], 16)
            label.setStyleSheet(
                f"color: {self._font_color}; "
                f"background-color: rgba({r}, {g}, {b}, 200); "
                "padding: 4px 8px; "
                "border-radius: 4px;"
            )
            label.adjustSize()
            # Position at bbox location, converting from pixels to points
            # OCR returns coordinates in captured image pixels (physical pixels)
            # Qt uses logical pixels, so divide by scale factor
            # Labels are positioned relative to the overlay widget
            x = int(bbox.get("x", 0) / scale) + window_offset_x + content_offset_x
            y = int(bbox.get("y", 0) / scale) + window_offset_y + content_offset_y
            label.move(x, y)
            label.show()
            self._labels.append(label)

    def position_over_window(self, bounds: dict):
        """Position overlay to cover a window.

        Args:
            bounds: Dict with x, y, width, height (in physical/screen pixels)
        """
        from PySide6.QtCore import QPoint

        # Find which screen the window is on based on its center point
        center_x = bounds["x"] + bounds["width"] // 2
        center_y = bounds["y"] + bounds["height"] // 2
        screen = QApplication.screenAt(QPoint(center_x, center_y))
        if screen is None:
            screen = QApplication.primaryScreen()

        scale = screen.devicePixelRatio()

        # On Linux/Wayland, we can't move windows programmatically.
        # Instead, keep the overlay fullscreen on the game's monitor and store
        # the window offset so labels can be positioned at absolute coordinates.
        if _system == "Linux":
            # Store bounds for label positioning (will be used in set_regions)
            self._window_bounds = bounds

            # Get the monitor geometry and store its offset
            screen_geom = screen.geometry()
            self._monitor_offset = (screen_geom.x(), screen_geom.y())

            # Position overlay to cover the entire monitor
            if self.geometry() != screen_geom:
                self.setGeometry(screen_geom)
            return

        # On Windows/macOS, position overlay directly over the window
        x = int(bounds["x"] / scale)
        y = int(bounds["y"] / scale)
        width = int(bounds["width"] / scale)
        height = int(bounds["height"] / scale)
        self.setGeometry(x, y, width, height)

    def set_font_size(self, size: int):
        """Update the font size."""
        self._font_size = size

    def set_colors(self, font_color: str, background_color: str):
        """Update the colors."""
        self._font_color = font_color
        self._background_color = background_color

    @property
    def font_size(self) -> int:
        return self._font_size

    def showEvent(self, event):
        """Handle show event - apply platform-specific settings."""
        super().showEvent(event)

        if _system == "Windows":
            # Windows: Set extended window style for click-through
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
                pass  # Ignore on non-Windows
