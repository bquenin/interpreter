"""Base classes for overlay windows.

Platform-specific implementations inherit from these base classes.
macOS and Windows use PySide6, Linux uses Tkinter (separate implementation).
"""

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QVBoxLayout, QWidget

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
        font_family: str | None = None,
        font_size: int = 24,
        font_color: str = "#FFFFFF",
        background_color: str = "#404040",
        background_opacity: float = 0.8,
    ):
        super().__init__()
        self._drag_pos: QPoint | None = None
        self._font_family = font_family  # None = system default
        self._font_size = font_size
        self._font_color = font_color
        self._background_color = background_color
        self._background_opacity = background_opacity
        self._setup_window()
        self._setup_ui()

    def _setup_window(self):
        """Configure window flags for overlay behavior."""
        # BypassWindowManagerHint - window manager won't manage this window at all
        # This gives us: no constraints, full positioning control, stays on top
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.BypassWindowManagerHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.Tool
        )

        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        # Use full screen width
        screen = QApplication.primaryScreen().geometry()
        self.resize(screen.width(), BANNER_HEIGHT)
        self._move_to_bottom()

    def _get_background_style(self) -> str:
        """Generate RGBA background style from color and opacity."""
        bg_color = self._background_color.lstrip("#")
        r, g, b = int(bg_color[0:2], 16), int(bg_color[2:4], 16), int(bg_color[4:6], 16)
        a = int(self._background_opacity * 255)
        return f"background-color: rgba({r}, {g}, {b}, {a});"

    def _setup_ui(self):
        """Set up the background frame and text label."""
        # Main layout with no margins (frame will fill entire window)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Background frame - this paints the semi-transparent background
        # (WA_TranslucentBackground makes the main widget transparent,
        # so we need a child widget to actually paint the background)
        self._background_frame = QFrame()
        self._background_frame.setStyleSheet(self._get_background_style())
        main_layout.addWidget(self._background_frame)

        # Layout inside the frame for the label
        frame_layout = QVBoxLayout(self._background_frame)
        frame_layout.setContentsMargins(20, 10, 20, 10)

        self._label = QLabel("")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setWordWrap(True)
        self._update_label_style()
        frame_layout.addWidget(self._label)

    def _create_font(self) -> QFont:
        """Create a font with current family and size settings."""
        if self._font_family:
            font = QFont(self._font_family)
        else:
            font = QFont()  # System default font
        font.setPointSize(self._font_size)
        font.setWeight(QFont.Weight.Bold)
        return font

    def _update_label_style(self):
        """Update label font and color."""
        self._label.setFont(self._create_font())
        self._label.setStyleSheet(f"color: {self._font_color}; background: transparent;")

    def _move_to_bottom(self):
        """Position at bottom of screen, full width."""
        screen = QApplication.primaryScreen().geometry()
        x = 0
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

    def set_font_family(self, font_family: str | None):
        """Update the font family. None = system default."""
        self._font_family = font_family
        self._update_label_style()
        self._resize_to_fit()

    def set_colors(self, font_color: str, background_color: str):
        """Update the colors."""
        self._font_color = font_color
        self._background_color = background_color
        self._background_frame.setStyleSheet(self._get_background_style())
        self._update_label_style()

    def set_opacity(self, opacity: float):
        """Update the background opacity (0.0-1.0)."""
        self._background_opacity = opacity
        self._background_frame.setStyleSheet(self._get_background_style())

    @property
    def font_size(self) -> int:
        return self._font_size

    def set_position(self, x: int, y: int):
        """Move banner to specific position."""
        self.move(x, y)

    def clamp_to_visible_area(self):
        """Ensure banner is at least partially visible on screen.

        If the banner is completely outside all available screens,
        move it to the bottom of the primary screen.
        """
        screen = QApplication.primaryScreen()
        if screen is None:
            return

        # Get the virtual desktop geometry (union of all screens)
        virtual_geometry = screen.virtualGeometry()

        # Get current banner geometry
        banner_rect = self.frameGeometry()

        # Check if banner intersects with the virtual desktop at all
        if not virtual_geometry.intersects(banner_rect):
            logger.info(
                "banner position out of bounds, resetting to primary screen",
                banner_x=banner_rect.x(),
                banner_y=banner_rect.y(),
                virtual_geometry=f"{virtual_geometry.x()},{virtual_geometry.y()} "
                f"{virtual_geometry.width()}x{virtual_geometry.height()}",
            )
            self._move_to_bottom()

    def get_position(self) -> tuple[int, int]:
        """Get current position (x, y)."""
        return (self.x(), self.y())

    def _resize_to_fit(self):
        """Resize banner height to fit current text content."""
        current_width = self.width()
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

        # Reset size constraints to allow shrinking
        self.setMinimumSize(0, 0)
        self.setMaximumSize(QWIDGETSIZE_MAX, QWIDGETSIZE_MAX)
        self._label.setMinimumSize(0, 0)
        self._label.setMaximumSize(QWIDGETSIZE_MAX, QWIDGETSIZE_MAX)

        # Set label width constraint for proper word wrapping
        self._label.setFixedWidth(label_width)

        # Apply final size
        self.setFixedSize(current_width, new_height)

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
        if self._drag_pos is not None:
            self._drag_pos = None
            event.accept()


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
        font_family: str | None = None,
        font_size: int = 18,
        font_color: str = "#FFFFFF",
        background_color: str = "#404040",
        background_opacity: float = 0.8,
    ):
        super().__init__()
        self._labels: list[QLabel] = []
        self._font_family = font_family  # None = system default
        self._font_size = font_size
        self._font_color = font_color
        self._background_color = background_color
        self._background_opacity = background_opacity
        self._last_regions: list[tuple[str, dict]] = []
        self._last_content_offset: tuple[int, int] = (0, 0)
        self._setup_window()

    def _setup_window(self):
        """Configure window flags for transparent, click-through overlay."""
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.BypassWindowManagerHint
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

    def _create_font(self) -> QFont:
        """Create a font with current family and size settings."""
        if self._font_family:
            font = QFont(self._font_family)
        else:
            font = QFont()  # System default font
        font.setPointSize(self._font_size)
        font.setWeight(QFont.Weight.Bold)
        return font

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
            label.setFont(self._create_font())
            # Convert hex background color to rgba with configurable transparency
            bg_color = self._background_color.lstrip("#")
            r, g, b = int(bg_color[0:2], 16), int(bg_color[2:4], 16), int(bg_color[4:6], 16)
            a = int(self._background_opacity * 255)
            label.setStyleSheet(
                f"color: {self._font_color}; "
                f"background-color: rgba({r}, {g}, {b}, {a}); "
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

    def set_font_family(self, font_family: str | None):
        """Update the font family and re-render immediately. None = system default."""
        self._font_family = font_family
        if self._last_regions:
            self.set_regions(self._last_regions, self._last_content_offset)

    def set_colors(self, font_color: str, background_color: str):
        """Update the colors and re-render immediately."""
        self._font_color = font_color
        self._background_color = background_color
        if self._last_regions:
            self.set_regions(self._last_regions, self._last_content_offset)

    def set_opacity(self, opacity: float):
        """Update the background opacity (0.0-1.0) and re-render immediately."""
        self._background_opacity = opacity
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
