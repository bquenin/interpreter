"""PySide6 overlay windows for banner and inplace modes."""

import platform
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QFont, QColor

_system = platform.system()


class BannerOverlay(QWidget):
    """Banner-style overlay at bottom of screen."""

    def __init__(self):
        super().__init__()
        self._drag_pos = None
        self._setup_window()
        self._setup_ui()

    def _setup_window(self):
        """Configure window flags for overlay behavior."""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool  # Hides from taskbar
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setStyleSheet("background-color: #404040;")

        # Initial size and position
        self.resize(800, 80)
        self._move_to_bottom()

    def _setup_ui(self):
        """Set up the text label."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 10, 20, 10)

        self.label = QLabel("Banner Overlay - Sample Text")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setWordWrap(True)
        self.label.setFont(QFont("Arial", 24, QFont.Weight.Bold))
        self.label.setStyleSheet("color: white; background: transparent;")
        layout.addWidget(self.label)

    def _move_to_bottom(self):
        """Position at bottom center of screen."""
        from PySide6.QtWidgets import QApplication
        screen = QApplication.primaryScreen().geometry()
        x = (screen.width() - self.width()) // 2
        y = screen.height() - self.height() - 50
        self.move(x, y)

    def set_text(self, text: str):
        """Update the displayed text."""
        self.label.setText(text)

    # Dragging support
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None


class InplaceOverlay(QWidget):
    """Transparent overlay for inplace text display."""

    def __init__(self):
        super().__init__()
        self._labels: list[QLabel] = []
        self._setup_window()

    def _setup_window(self):
        """Configure window flags for transparent, click-through overlay."""
        flags = (
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )

        # Platform-specific click-through
        if _system == "Darwin":
            # macOS: WindowTransparentForInput makes it click-through
            flags |= Qt.WindowType.WindowTransparentForInput
        elif _system == "Windows":
            # Windows: Need to set extended style after window creation
            flags |= Qt.WindowType.WindowTransparentForInput
        elif _system == "Linux":
            # Linux/X11: WindowTransparentForInput should work
            flags |= Qt.WindowType.WindowTransparentForInput

        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        # Full screen size by default
        from PySide6.QtWidgets import QApplication
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)

    def set_regions(self, regions: list[dict]):
        """Update text regions.

        Args:
            regions: List of dicts with 'text', 'x', 'y' keys
        """
        # Remove old labels
        for label in self._labels:
            label.deleteLater()
        self._labels.clear()

        # Create new labels
        for region in regions:
            label = QLabel(region.get("text", ""), self)
            label.setFont(QFont("Arial", 18, QFont.Weight.Bold))
            label.setStyleSheet(
                "color: white; "
                "background-color: rgba(0, 0, 0, 180); "
                "padding: 4px 8px; "
                "border-radius: 4px;"
            )
            label.adjustSize()
            label.move(region.get("x", 0), region.get("y", 0))
            label.show()
            self._labels.append(label)

    def position_over_window(self, bounds: dict):
        """Position overlay to cover a window.

        Args:
            bounds: Dict with x, y, width, height
        """
        self.setGeometry(
            bounds["x"],
            bounds["y"],
            bounds["width"],
            bounds["height"]
        )

    def showEvent(self, event):
        """Handle show event - apply platform-specific settings."""
        super().showEvent(event)

        if _system == "Windows":
            # Windows: Set extended window style for click-through
            try:
                import ctypes
                from ctypes import wintypes
                hwnd = int(self.winId())
                GWL_EXSTYLE = -20
                WS_EX_TRANSPARENT = 0x00000020
                WS_EX_LAYERED = 0x00080000
                user32 = ctypes.windll.user32
                style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_TRANSPARENT | WS_EX_LAYERED)
            except Exception:
                pass  # Ignore on non-Windows
