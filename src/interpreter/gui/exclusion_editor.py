"""Exclusion zone editor dialog for defining areas to exclude from OCR."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QGraphicsItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from ..capture.convert import bgra_to_rgb_pil


class ExclusionZoneItem(QGraphicsRectItem):
    """Interactive rectangle item for exclusion zones."""

    HANDLE_SIZE = 8
    MIN_SIZE = 20

    def __init__(self, rect: QRectF):
        super().__init__(rect)
        self._resize_handle = None
        self._drag_start = None

        # Semi-transparent red fill
        self.setBrush(QBrush(QColor(255, 0, 0, 80)))
        self.setPen(QPen(QColor(255, 0, 0, 200), 2))

        # Ensure zones appear above the background pixmap
        self.setZValue(1)

        # Make selectable and movable
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)

    def paint(self, painter, option, widget=None):
        """Paint the rectangle with resize handles when selected."""
        super().paint(painter, option, widget)

        if self.isSelected():
            # Draw resize handles at corners
            handle_brush = QBrush(QColor(255, 255, 255))
            handle_pen = QPen(QColor(0, 0, 0), 1)
            painter.setBrush(handle_brush)
            painter.setPen(handle_pen)

            rect = self.rect()
            handles = self._get_handle_rects(rect)
            for handle_rect in handles.values():
                painter.drawRect(handle_rect)

    def _get_handle_rects(self, rect: QRectF) -> dict:
        """Get rectangles for resize handles at each corner."""
        hs = self.HANDLE_SIZE
        return {
            "top_left": QRectF(rect.left() - hs / 2, rect.top() - hs / 2, hs, hs),
            "top_right": QRectF(rect.right() - hs / 2, rect.top() - hs / 2, hs, hs),
            "bottom_left": QRectF(rect.left() - hs / 2, rect.bottom() - hs / 2, hs, hs),
            "bottom_right": QRectF(rect.right() - hs / 2, rect.bottom() - hs / 2, hs, hs),
        }

    def hoverMoveEvent(self, event):
        """Change cursor when hovering over resize handles."""
        if self.isSelected():
            handles = self._get_handle_rects(self.rect())
            pos = event.pos()
            for name, handle_rect in handles.items():
                if handle_rect.contains(pos):
                    if name in ("top_left", "bottom_right"):
                        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
                    else:
                        self.setCursor(Qt.CursorShape.SizeBDiagCursor)
                    return
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event):
        """Start resize if clicking on a handle."""
        if self.isSelected() and event.button() == Qt.MouseButton.LeftButton:
            handles = self._get_handle_rects(self.rect())
            pos = event.pos()
            for name, handle_rect in handles.items():
                if handle_rect.contains(pos):
                    self._resize_handle = name
                    self._drag_start = pos
                    event.accept()
                    return
        self._resize_handle = None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Handle resize or move."""
        if self._resize_handle:
            rect = self.rect()
            pos = event.pos()

            if self._resize_handle == "top_left":
                new_rect = QRectF(pos.x(), pos.y(), rect.right() - pos.x(), rect.bottom() - pos.y())
            elif self._resize_handle == "top_right":
                new_rect = QRectF(rect.left(), pos.y(), pos.x() - rect.left(), rect.bottom() - pos.y())
            elif self._resize_handle == "bottom_left":
                new_rect = QRectF(pos.x(), rect.top(), rect.right() - pos.x(), pos.y() - rect.top())
            else:  # bottom_right
                new_rect = QRectF(rect.left(), rect.top(), pos.x() - rect.left(), pos.y() - rect.top())

            # Enforce minimum size
            if new_rect.width() >= self.MIN_SIZE and new_rect.height() >= self.MIN_SIZE:
                self.setRect(new_rect.normalized())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """End resize."""
        if self._resize_handle:
            self._resize_handle = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def itemChange(self, change, value):
        """Handle item changes like selection."""
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            # Update appearance
            if value:
                self.setPen(QPen(QColor(255, 100, 100, 255), 3))
            else:
                self.setPen(QPen(QColor(255, 0, 0, 200), 2))
        return super().itemChange(change, value)


class ExclusionEditorDialog(QDialog):
    """Dialog for editing exclusion zones on the captured image."""

    MAX_PREVIEW_WIDTH = 1200
    MAX_PREVIEW_HEIGHT = 900

    def __init__(self, parent=None, initial_zones: list | None = None):
        super().__init__(parent)
        self.setWindowTitle("Edit Exclusion Zones")

        self._zones: list[ExclusionZoneItem] = []
        self._drawing = False
        self._draw_start = None
        self._current_draw_rect = None
        self._image_size = (0, 0)  # Original image size
        self._preview_size = (0, 0)  # Scaled preview size

        self._setup_ui()

        # Load initial zones
        if initial_zones:
            self._load_zones(initial_zones)

    def _setup_ui(self):
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        # Instructions
        instructions = QLabel("Click and drag to draw exclusion zones. Click to select, Delete/Backspace to remove.")
        instructions.setStyleSheet("color: #ccc; font-size: 14px; padding: 5px 0;")
        layout.addWidget(instructions)

        # Graphics scene and view
        self._scene = QGraphicsScene()
        self._view = QGraphicsView(self._scene)
        self._view.setRenderHints(self._view.renderHints())
        self._view.setDragMode(QGraphicsView.DragMode.NoDrag)
        self._view.setMouseTracking(True)
        self._view.viewport().installEventFilter(self)
        layout.addWidget(self._view)

        # Bottom buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        clear_btn = QPushButton("Clear All")
        clear_btn.clicked.connect(self._clear_all)
        btn_layout.addWidget(clear_btn)

        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

    def eventFilter(self, obj, event):
        """Handle mouse events on the graphics view."""
        from PySide6.QtCore import QEvent

        if obj == self._view.viewport():
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.LeftButton:
                    scene_pos = self._view.mapToScene(event.pos())
                    # Check if clicking on an existing zone
                    item = self._scene.itemAt(scene_pos, self._view.transform())
                    if isinstance(item, ExclusionZoneItem):
                        # Let the item handle selection
                        return False
                    # Start drawing new zone
                    self._drawing = True
                    self._draw_start = scene_pos
                    self._current_draw_rect = QGraphicsRectItem()
                    self._current_draw_rect.setBrush(QBrush(QColor(255, 0, 0, 40)))
                    self._current_draw_rect.setPen(QPen(QColor(255, 0, 0, 150), 1, Qt.PenStyle.DashLine))
                    self._current_draw_rect.setZValue(2)  # Above zones during drawing
                    self._scene.addItem(self._current_draw_rect)
                    return True

            elif event.type() == QEvent.Type.MouseMove:
                if self._drawing and self._draw_start:
                    scene_pos = self._view.mapToScene(event.pos())
                    rect = QRectF(self._draw_start, scene_pos).normalized()
                    self._current_draw_rect.setRect(rect)
                    return True

            elif event.type() == QEvent.Type.MouseButtonRelease:
                if self._drawing and event.button() == Qt.MouseButton.LeftButton:
                    self._drawing = False
                    if self._current_draw_rect:
                        rect = self._current_draw_rect.rect()
                        self._scene.removeItem(self._current_draw_rect)
                        self._current_draw_rect = None
                        # Only create zone if large enough
                        if rect.width() >= ExclusionZoneItem.MIN_SIZE and rect.height() >= ExclusionZoneItem.MIN_SIZE:
                            self._add_zone(rect)
                    self._draw_start = None
                    return True

        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        """Handle key presses."""
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self._delete_selected()
        else:
            super().keyPressEvent(event)

    def update_frame(self, frame):
        """Update the preview with a new frame.

        Args:
            frame: BGRA numpy array (H, W, 4)
        """
        if frame is None:
            return

        # Store original image size
        h, w = frame.shape[:2]
        self._image_size = (w, h)

        # Convert to PIL and scale for preview
        pil_image = bgra_to_rgb_pil(frame)

        # Scale to fit preview area while maintaining aspect ratio
        scale_x = self.MAX_PREVIEW_WIDTH / w
        scale_y = self.MAX_PREVIEW_HEIGHT / h
        scale = min(scale_x, scale_y)

        new_w = int(w * scale)
        new_h = int(h * scale)

        pil_image = pil_image.resize((new_w, new_h))

        # Convert to QPixmap
        data = pil_image.tobytes("raw", "RGB")
        qimg = QImage(data, new_w, new_h, new_w * 3, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg)

        # Update scene background
        # Remove old pixmap items (keep zone items)
        for item in self._scene.items():
            if not isinstance(item, ExclusionZoneItem) and item != self._current_draw_rect:
                self._scene.removeItem(item)

        pixmap_item = self._scene.addPixmap(pixmap)
        pixmap_item.setZValue(0)  # Keep pixmap behind zones
        self._scene.setSceneRect(0, 0, new_w, new_h)

        # Auto-size dialog to fit preview on first frame
        if self._preview_size == (0, 0):
            self._preview_size = (new_w, new_h)
            # Add padding for margins, instructions, and buttons
            dialog_w = new_w + 40
            dialog_h = new_h + 100
            self.resize(dialog_w, dialog_h)
            self._view.setFixedSize(new_w + 4, new_h + 4)  # Small padding for border

    def _add_zone(self, rect: QRectF):
        """Add a new exclusion zone."""
        zone_item = ExclusionZoneItem(rect)
        self._scene.addItem(zone_item)
        self._zones.append(zone_item)

    def _load_zones(self, zones: list):
        """Load zones from normalized coordinates."""
        # This will be called after the first frame update
        self._pending_zones = zones

    def apply_pending_zones(self):
        """Apply pending zones after image is loaded."""
        if not hasattr(self, "_pending_zones") or not self._pending_zones:
            return

        w, h = self._image_size
        if w == 0 or h == 0:
            return

        # Get current scene size (scaled preview)
        scene_rect = self._scene.sceneRect()
        scale_x = scene_rect.width() / w if w > 0 else 1
        scale_y = scene_rect.height() / h if h > 0 else 1

        for zone_data in self._pending_zones:
            x = zone_data.get("x", 0) * w * scale_x
            y = zone_data.get("y", 0) * h * scale_y
            width = zone_data.get("width", 0.1) * w * scale_x
            height = zone_data.get("height", 0.1) * h * scale_y
            rect = QRectF(x, y, width, height)
            self._add_zone(rect)

        self._pending_zones = []

    def _delete_selected(self):
        """Delete selected zones."""
        selected_items = [z for z in self._zones if z.isSelected()]
        for zone_item in selected_items:
            self._scene.removeItem(zone_item)
            self._zones.remove(zone_item)

    def _clear_all(self):
        """Remove all zones."""
        for zone_item in self._zones:
            self._scene.removeItem(zone_item)
        self._zones.clear()

    def get_zones(self) -> list[dict]:
        """Get zones as normalized coordinates.

        Returns:
            List of zone dicts with x, y, width, height as floats (0.0-1.0).
        """
        w, h = self._image_size
        if w == 0 or h == 0:
            return []

        # Get current scene size to calculate scale
        scene_rect = self._scene.sceneRect()
        scale_x = w / scene_rect.width() if scene_rect.width() > 0 else 1
        scale_y = h / scene_rect.height() if scene_rect.height() > 0 else 1

        zones = []
        for zone_item in self._zones:
            rect = zone_item.rect()
            # Convert scene coordinates back to normalized
            pos = zone_item.pos()  # Position offset from item transformations
            zones.append(
                {
                    "x": (rect.x() + pos.x()) * scale_x / w,
                    "y": (rect.y() + pos.y()) * scale_y / h,
                    "width": rect.width() * scale_x / w,
                    "height": rect.height() * scale_y / h,
                }
            )
        return zones
