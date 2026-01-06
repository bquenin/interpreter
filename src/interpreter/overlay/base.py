"""Base classes for overlay windows.

Platform-specific implementations inherit from these base classes.
macOS and Windows use PySide6, Linux uses Tkinter (separate implementation).
"""

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from .. import log

logger = log.get_logger()

# Banner overlay dimensions
BANNER_HEIGHT = 100
BANNER_BOTTOM_MARGIN = 50
BANNER_HORIZONTAL_PADDING = 60
BANNER_VERTICAL_PADDING = 30

# Qt maximum widget size (not exposed in PySide6, defined as (1 << 24) - 1 in C++)
QWIDGETSIZE_MAX = 16777215


class BannerOverlayBase(QWidget):
    """Banner-style overlay at bottom of screen.

    A draggable subtitle bar that displays translated text.
    This base class is fully functional and typically doesn't need
    platform-specific overrides.
    """

    def __init__(
        self,
        font_family: str = "Helvetica",
        font_size: int = 24,
        font_color: str = "#FFFFFF",
        background_color: str = "#404040",
    ):
        super().__init__()
        self._drag_pos: QPoint | None = None
        self._font_family = font_family
        self._font_size = font_size
        self._font_color = font_color
        self._background_color = background_color
        self._setup_window()
        self._setup_ui()

    def _setup_window(self):
        """Configure window flags for overlay behavior."""
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.Tool  # Hides from taskbar
        )

        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        self.setStyleSheet(f"background-color: {self._background_color};")

        # Use full screen width
        screen = QApplication.primaryScreen().geometry()
        self.resize(screen.width(), BANNER_HEIGHT)
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
        self._label.setFont(QFont(self._font_family, self._font_size, QFont.Weight.Bold))
        self._label.setStyleSheet(f"color: {self._font_color}; background: transparent;")

    def _move_to_bottom(self):
        """Position at bottom of screen."""
        screen = QApplication.primaryScreen().geometry()
        x = 0  # Full width, start at left edge
        y = screen.height() - self.height() - BANNER_BOTTOM_MARGIN
        self.move(x, y)

    def set_text(self, text: str):
        """Update the displayed text."""
        self._label.setText(text)
        self._resize_to_fit()

    def set_font_size(self, size: int):
        """Update the font size."""
        self._font_size = size
        self._update_label_style()
        self._resize_to_fit()

    def set_colors(self, font_color: str, background_color: str):
        """Update the colors."""
        self._font_color = font_color
        self._background_color = background_color
        self.setStyleSheet(f"background-color: {self._background_color};")
        self._update_label_style()

    @property
    def font_size(self) -> int:
        return self._font_size

    def set_position(self, x: int, y: int):
        """Move banner to specific position and resize to match screen."""
        logger.debug("qt set_position", x=x, y=y)

        # Find which screen this position is on
        # Use x,y directly since widget may not be at correct position yet
        screen = QApplication.screenAt(QPoint(x, y))
        if screen is None:
            screen = QApplication.primaryScreen()

        screen_geom = screen.geometry()
        screen_width = screen_geom.width()

        logger.debug(
            "set_position screen detection",
            screen_x=screen_geom.x(),
            screen_width=screen_width,
            current_width=self.width(),
        )

        # Reset constraints and set geometry atomically
        self.setMinimumSize(0, 0)
        self.setMaximumSize(QWIDGETSIZE_MAX, QWIDGETSIZE_MAX)

        # Snap X to screen left edge, keep Y as requested
        new_x = screen_geom.x()
        self.setGeometry(new_x, y, screen_width, self.height())

    def get_position(self) -> tuple[int, int]:
        """Get current position (x, y)."""
        pos = (self.x(), self.y())
        logger.debug("qt get_position", x=pos[0], y=pos[1])
        return pos

    # Snap to screen
    _snap_to_screen: bool = True

    def _resize_to_fit(self, keep_bottom_fixed: bool = True):
        """Resize banner height to fit current text content.

        Args:
            keep_bottom_fixed: If True, grow/shrink upward keeping bottom edge fixed.
                              If False, only resize without moving.
        """
        current_width = self.width()
        current_y = self.y()
        current_height = self.height()

        # Calculate required height from label + layout margins
        label_width = current_width - 40  # Account for layout margins (20px each side)

        # Use heightForWidth for accurate word-wrapped height calculation
        label_height = self._label.heightForWidth(label_width)
        if label_height < 0:
            # Fallback if heightForWidth not supported
            label_height = self._label.sizeHint().height()
        new_height = label_height + 20  # Account for layout margins (10px top/bottom)

        # Skip resize if height hasn't changed
        if new_height == current_height:
            return

        logger.debug(
            "_resize_to_fit",
            current_width=current_width,
            current_height=current_height,
            label_width=label_width,
            label_height=label_height,
            new_height=new_height,
        )

        # Reset size constraints to allow shrinking
        self.setMinimumSize(0, 0)
        self.setMaximumSize(QWIDGETSIZE_MAX, QWIDGETSIZE_MAX)
        self._label.setMinimumSize(0, 0)
        self._label.setMaximumSize(QWIDGETSIZE_MAX, QWIDGETSIZE_MAX)

        # Set label width constraint for proper word wrapping
        self._label.setFixedWidth(label_width)

        # Apply final size
        self.setFixedSize(current_width, new_height)

        # Keep bottom edge fixed (grow/shrink upward) if requested
        if keep_bottom_fixed:
            new_y = current_y + current_height - new_height
            self.move(self.x(), new_y)

    # Dragging support
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            logger.debug(
                "mousePressEvent",
                drag_pos=str(self._drag_pos),
                geometry=f"{self.x()},{self.y()} {self.width()}x{self.height()}",
            )
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        logger.debug(
            "mouseReleaseEvent",
            had_drag_pos=self._drag_pos is not None,
            geometry=f"{self.x()},{self.y()} {self.width()}x{self.height()}",
        )
        if self._drag_pos is not None:
            self._drag_pos = None
            self._snap_to_current_screen()

    def _snap_to_current_screen(self):
        """Snap banner to current screen bounds after drag."""
        if not self._snap_to_screen:
            return

        # Find which screen the banner center is on
        center = self.frameGeometry().center()
        screen = QApplication.screenAt(center)
        if screen is None:
            screen = QApplication.primaryScreen()

        screen_geom = screen.geometry()
        current_y = self.y()

        logger.debug(
            "snap_to_current_screen BEFORE",
            x=self.x(),
            y=self.y(),
            width=self.width(),
            height=self.height(),
            screen_x=screen_geom.x(),
            screen_y=screen_geom.y(),
            screen_width=screen_geom.width(),
            screen_height=screen_geom.height(),
        )

        # Calculate new dimensions
        new_width = screen_geom.width()
        new_x = screen_geom.x()

        # Check if we're moving to a different screen (cross-DPI transition)
        current_screen = QApplication.screenAt(self.frameGeometry().center())
        is_cross_screen = current_screen is None or current_screen != screen

        # Hide during cross-screen transition to avoid DPI scaling flash
        was_visible = self.isVisible()
        if is_cross_screen and was_visible:
            self.hide()

        # Reset ALL size constraints
        self.setMinimumSize(0, 0)
        self.setMaximumSize(QWIDGETSIZE_MAX, QWIDGETSIZE_MAX)
        self._label.setMinimumSize(0, 0)
        self._label.setMaximumSize(QWIDGETSIZE_MAX, QWIDGETSIZE_MAX)

        # Move and resize width
        self.move(new_x, current_y)
        self.resize(new_width, self.height())

        # Update label width for new screen
        label_width = new_width - 40
        self._label.setFixedWidth(label_width)

        # Force immediate height recalculation
        self._resize_to_fit(keep_bottom_fixed=False)

        # Clamp Y to screen bounds after height is calculated
        new_y = max(
            screen_geom.y(),
            min(current_y, screen_geom.y() + screen_geom.height() - self.height())
        )
        self.move(new_x, new_y)

        # Show again if was visible
        if is_cross_screen and was_visible:
            self.show()

        logger.debug(
            "snap_to_current_screen AFTER",
            x=self.x(),
            y=self.y(),
            width=self.width(),
            height=self.height(),
        )


class InplaceOverlayBase(QWidget):
    """Transparent overlay for inplace text display.

    A click-through overlay that positions translated text
    directly over the original game text.

    Subclasses must implement:
    - position_over_window(): Platform-specific coordinate handling
    - _apply_click_through(): Platform-specific click-through setup (optional)
    """

    def __init__(
        self,
        font_family: str = "Helvetica",
        font_size: int = 18,
        font_color: str = "#FFFFFF",
        background_color: str = "#404040",
    ):
        super().__init__()
        self._labels: list[QLabel] = []
        self._font_family = font_family
        self._font_size = font_size
        self._font_color = font_color
        self._background_color = background_color
        self._last_regions: list[tuple[str, dict]] = []
        self._last_content_offset: tuple[int, int] = (0, 0)
        self._setup_window()

    def _setup_window(self):
        """Configure window flags for transparent, click-through overlay."""
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.Tool
        )

        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        # Full screen size by default
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)

    def _clear_labels(self):
        """Remove all labels from the overlay."""
        for label in self._labels:
            label.hide()
            label.setParent(None)
            label.deleteLater()
        self._labels.clear()

    def _get_scale_factor(self) -> float:
        """Get the display scale factor for coordinate conversion.

        Returns:
            Scale factor (e.g., 2.0 for Retina displays).
        """
        screen = self.screen()
        if screen is None:
            screen = QApplication.primaryScreen()
        return screen.devicePixelRatio()

    def set_regions(self, regions: list[tuple[str, dict]], content_offset: tuple[int, int] = (0, 0)):
        """Update text regions.

        Args:
            regions: List of (text, bbox) tuples where bbox is a dict with x, y, width, height.
                     Coordinates are in captured image pixels (physical pixels).
            content_offset: Tuple of (x, y) offset in pixels for content area within window.
        """
        scale = self._get_scale_factor()

        # Convert content offset from pixels to points
        content_offset_x = int(content_offset[0] / scale)
        content_offset_y = int(content_offset[1] / scale)

        self._clear_labels()

        # Create new labels
        for text, bbox in regions:
            if not bbox:
                continue
            label = QLabel(text, self)
            label.setFont(QFont(self._font_family, self._font_size, QFont.Weight.Bold))
            # Convert hex background color to rgba with transparency
            bg_color = self._background_color.lstrip("#")
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
            # Qt uses logical pixels (points), so divide by scale factor
            x = int(bbox.get("x", 0) / scale) + content_offset_x
            y = int(bbox.get("y", 0) / scale) + content_offset_y
            label.move(x, y)
            label.show()
            self._labels.append(label)

        # Cache for immediate re-render on style changes
        self._last_regions = regions
        self._last_content_offset = content_offset

    def position_over_window(self, bounds: dict):
        """Position overlay to cover a window.

        This method MUST be implemented by platform-specific subclasses
        because coordinate systems differ:
        - macOS: CGWindowBounds returns points (logical pixels)
        - Windows: Window bounds are in physical pixels

        Args:
            bounds: Dict with x, y, width, height from platform capture.
        """
        raise NotImplementedError("Subclasses must implement position_over_window()")

    def clear_regions(self):
        """Clear all displayed text regions."""
        self._clear_labels()
        self._last_regions = []

    def set_font_size(self, size: int):
        """Update the font size and re-render immediately."""
        self._font_size = size
        if self._last_regions:
            self.set_regions(self._last_regions, self._last_content_offset)

    def set_colors(self, font_color: str, background_color: str):
        """Update the colors and re-render immediately."""
        self._font_color = font_color
        self._background_color = background_color
        if self._last_regions:
            self.set_regions(self._last_regions, self._last_content_offset)

    @property
    def font_size(self) -> int:
        return self._font_size

    def showEvent(self, event):
        """Handle show event - subclasses can override for platform-specific setup."""
        super().showEvent(event)
        self._apply_click_through()

    def _apply_click_through(self):
        """Apply platform-specific click-through behavior.

        Override in subclasses that need special handling (e.g., Windows).
        """
        pass
