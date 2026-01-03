"""Main application window with settings and controls."""

import time
from typing import Optional

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QComboBox, QPushButton, QGroupBox, QSlider,
    QFrame, QColorDialog, QButtonGroup, QKeySequenceEdit,
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap, QImage, QKeySequence

from pynput import keyboard

from ..capture import WindowCapture
from ..config import Config
from ..ocr import OCR
from ..translate import Translator
from .overlay import BannerOverlay, InplaceOverlay
from .workers import CaptureWorker, ProcessWorker


class MainWindow(QMainWindow):
    """Main application window."""

    # Signal for thread-safe hotkey handling
    hotkey_pressed = Signal()

    def __init__(self, config: Config):
        super().__init__()
        self._config = config

        self.setWindowTitle("Interpreter")
        self.setMinimumSize(500, 600)

        # State
        self._capturing = False
        self._mode = config.overlay_mode
        self._windows_list: list[dict] = []
        self._paused = False

        # Components
        self._capture: Optional[WindowCapture] = None
        self._ocr: Optional[OCR] = None
        self._translator: Optional[Translator] = None

        # Workers
        self._capture_worker = CaptureWorker()
        self._capture_worker.frame_ready.connect(self._on_frame)

        self._process_worker = ProcessWorker()
        self._process_worker.text_ready.connect(self._on_text_ready)
        self._process_worker.regions_ready.connect(self._on_regions_ready)

        # Overlays
        self._banner_overlay = BannerOverlay(
            font_size=config.font_size,
            font_color=config.font_color,
            background_color=config.background_color,
        )
        self._inplace_overlay = InplaceOverlay(
            font_size=config.font_size,
            font_color=config.font_color,
            background_color=config.background_color,
        )

        # Processing timer (respects refresh rate)
        self._process_timer = QTimer()
        self._process_timer.timeout.connect(self._process_frame)
        self._last_frame = None
        self._last_bounds = {}

        self._setup_ui()
        self._refresh_windows()
        self._load_models()

    def _setup_ui(self):
        """Set up the main UI."""
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # Window Selection
        window_group = QGroupBox("Window Selection")
        window_layout = QHBoxLayout(window_group)

        self._window_combo = QComboBox()
        self._window_combo.setMinimumWidth(250)
        window_layout.addWidget(self._window_combo, 1)

        self._start_btn = QPushButton("Start Capture")
        self._start_btn.clicked.connect(self._toggle_capture)
        window_layout.addWidget(self._start_btn)

        refresh_btn = QPushButton("Refresh List")
        refresh_btn.clicked.connect(self._refresh_windows)
        window_layout.addWidget(refresh_btn)

        layout.addWidget(window_group)

        # Overlay Settings
        overlay_group = QGroupBox("Overlay Settings")
        overlay_layout = QHBoxLayout(overlay_group)

        # Segmented mode selector
        overlay_layout.addWidget(QLabel("Mode:"))

        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)

        self._banner_btn = QPushButton("Banner")
        self._banner_btn.setCheckable(True)
        self._banner_btn.setChecked(self._mode == "banner")
        self._mode_group.addButton(self._banner_btn, 0)

        self._inplace_btn = QPushButton("Inplace")
        self._inplace_btn.setCheckable(True)
        self._inplace_btn.setChecked(self._mode == "inplace")
        self._mode_group.addButton(self._inplace_btn, 1)

        # Style as segmented control (dark mode friendly)
        segment_style = """
            QPushButton {
                padding: 6px 16px;
                border: 1px solid #555;
                background-color: #3a3a3a;
                color: #ccc;
            }
            QPushButton:checked {
                background-color: #0078d4;
                color: white;
                border-color: #0078d4;
            }
            QPushButton:hover:!checked {
                background-color: #4a4a4a;
            }
        """
        self._banner_btn.setStyleSheet(segment_style + "QPushButton { border-radius: 4px 0 0 4px; border-right: none; }")
        self._inplace_btn.setStyleSheet(segment_style + "QPushButton { border-radius: 0 4px 4px 0; }")

        self._mode_group.idClicked.connect(self._on_mode_changed)

        # Container to keep buttons connected (no spacing)
        mode_container = QWidget()
        mode_layout = QHBoxLayout(mode_container)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(0)
        mode_layout.addWidget(self._banner_btn)
        mode_layout.addWidget(self._inplace_btn)
        overlay_layout.addWidget(mode_container)

        overlay_layout.addStretch()

        self._pause_btn = QPushButton("Pause")
        self._pause_btn.clicked.connect(self._toggle_pause)
        self._pause_btn.setEnabled(False)
        overlay_layout.addWidget(self._pause_btn)

        # Hotkey picker for pause
        self._pause_hotkey = QKeySequenceEdit(QKeySequence(Qt.Key.Key_Space))
        self._pause_hotkey.setFixedWidth(80)
        self._pause_hotkey.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._pause_hotkey.keySequenceChanged.connect(self._on_pause_hotkey_changed)
        overlay_layout.addWidget(self._pause_hotkey)

        # Global hotkey using pynput
        self._current_hotkey = keyboard.Key.space
        self._keyboard_listener = keyboard.Listener(on_press=self._on_key_press)
        self._keyboard_listener.start()
        self.hotkey_pressed.connect(self._toggle_pause)

        layout.addWidget(overlay_group)

        # Settings
        settings_group = QGroupBox("Settings")
        settings_layout = QGridLayout(settings_group)

        # Refresh rate
        settings_layout.addWidget(QLabel("Refresh Rate:"), 0, 0)
        self._refresh_slider = QSlider(Qt.Orientation.Horizontal)
        self._refresh_slider.setRange(1, 20)  # 0.1 to 2.0 seconds
        self._refresh_slider.setValue(int(self._config.refresh_rate * 10))
        self._refresh_slider.valueChanged.connect(self._on_refresh_rate_changed)
        settings_layout.addWidget(self._refresh_slider, 0, 1)
        self._refresh_label = QLabel(f"{self._config.refresh_rate:.1f}s")
        settings_layout.addWidget(self._refresh_label, 0, 2)

        # OCR Confidence
        settings_layout.addWidget(QLabel("OCR Confidence:"), 1, 0)
        self._confidence_slider = QSlider(Qt.Orientation.Horizontal)
        self._confidence_slider.setRange(0, 100)
        self._confidence_slider.setValue(int(self._config.ocr_confidence * 100))
        self._confidence_slider.valueChanged.connect(self._on_confidence_changed)
        settings_layout.addWidget(self._confidence_slider, 1, 1)
        self._confidence_label = QLabel(f"{self._config.ocr_confidence:.0%}")
        settings_layout.addWidget(self._confidence_label, 1, 2)

        # Font size
        settings_layout.addWidget(QLabel("Font Size:"), 2, 0)
        self._font_slider = QSlider(Qt.Orientation.Horizontal)
        self._font_slider.setRange(8, 72)
        self._font_slider.setValue(self._config.font_size)
        self._font_slider.valueChanged.connect(self._on_font_size_changed)
        settings_layout.addWidget(self._font_slider, 2, 1)
        self._font_label = QLabel(f"{self._config.font_size}pt")
        settings_layout.addWidget(self._font_label, 2, 2)

        # Colors
        settings_layout.addWidget(QLabel("Font Color:"), 3, 0)
        self._font_color_btn = QPushButton()
        self._font_color_btn.setStyleSheet(f"background-color: {self._config.font_color};")
        self._font_color_btn.clicked.connect(self._pick_font_color)
        settings_layout.addWidget(self._font_color_btn, 3, 1)

        settings_layout.addWidget(QLabel("Background:"), 4, 0)
        self._bg_color_btn = QPushButton()
        self._bg_color_btn.setStyleSheet(f"background-color: {self._config.background_color};")
        self._bg_color_btn.clicked.connect(self._pick_bg_color)
        settings_layout.addWidget(self._bg_color_btn, 4, 1)

        layout.addWidget(settings_group)

        # Status
        status_group = QGroupBox("Status")
        status_layout = QVBoxLayout(status_group)

        self._status_label = QLabel("Status: Idle")
        status_layout.addWidget(self._status_label)

        self._fps_label = QLabel("FPS: --")
        status_layout.addWidget(self._fps_label)

        # Preview
        self._preview_label = QLabel()
        self._preview_label.setFixedSize(320, 240)
        self._preview_label.setFrameStyle(QFrame.Shape.Box)
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setText("No preview")
        self._preview_label.setStyleSheet("background-color: #2a2a2a; color: #888;")
        status_layout.addWidget(self._preview_label)

        layout.addWidget(status_group)

        # Stretch at bottom
        layout.addStretch()

    def _load_models(self):
        """Load OCR and translation models."""
        self._status_label.setText("Status: Loading models...")
        self.repaint()

        # Load OCR
        self._ocr = OCR(confidence_threshold=self._config.ocr_confidence)
        self._ocr.load()

        # Load translator
        self._translator = Translator()
        self._translator.load()

        self._process_worker.set_ocr(self._ocr)
        self._process_worker.set_translator(self._translator)
        self._process_worker.set_mode(self._mode)  # Sync mode from config

        self._status_label.setText("Status: Ready")

    def _refresh_windows(self):
        """Refresh the window list."""
        self._windows_list = WindowCapture.list_windows()
        self._window_combo.clear()

        selected_idx = -1
        for i, win in enumerate(self._windows_list):
            title = win.get("title", "Unknown")
            bounds = win.get("bounds", {})
            width = bounds.get("width", 0)
            height = bounds.get("height", 0)
            if len(title) > 50:
                title = title[:50] + "..."
            display_text = f"{title} ({width}x{height})"
            self._window_combo.addItem(display_text)

            # Auto-select if matches config
            if self._config.window_title and self._config.window_title.lower() in win.get("title", "").lower():
                selected_idx = i

        if selected_idx >= 0:
            self._window_combo.setCurrentIndex(selected_idx)

    def _toggle_capture(self):
        """Start or stop capture."""
        if self._capturing:
            self._stop_capture()
        else:
            self._start_capture()

    def _start_capture(self):
        """Start capturing the selected window."""
        idx = self._window_combo.currentIndex()
        if idx < 0 or idx >= len(self._windows_list):
            self._status_label.setText("Status: No window selected")
            return

        window = self._windows_list[idx]
        title = window.get("title", "")
        window_id = window.get("id")
        bounds = window.get("bounds")

        self._capture = WindowCapture(title, window_id=window_id, bounds=bounds)
        if not self._capture.find_window():
            self._status_label.setText("Status: Window not found")
            return

        if not self._capture.start_stream():
            self._status_label.setText("Status: Failed to start stream")
            return

        self._capture_worker.set_capture(self._capture)
        self._capture_worker.start()

        # Start process timer based on refresh rate
        interval_ms = int(self._config.refresh_rate * 1000)
        self._process_timer.setInterval(interval_ms)
        self._process_timer.start()

        self._capturing = True
        self._paused = False
        self._start_btn.setText("Stop Capture")
        self._pause_btn.setEnabled(True)
        self._pause_btn.setText("Pause")
        self._status_label.setText(f"Status: Capturing '{title[:40]}...'")

        # Update config with selected window
        self._config.window_title = title

        # Show overlay
        self._show_overlay()

    def _stop_capture(self):
        """Stop capturing."""
        self._capture_worker.stop()
        self._process_timer.stop()

        if self._capture:
            self._capture.stop_stream()
            self._capture = None

        self._capturing = False
        self._paused = False
        self._start_btn.setText("Start Capture")
        self._pause_btn.setEnabled(False)
        self._status_label.setText("Status: Idle")
        self._fps_label.setText("FPS: --")

        # Clear preview
        self._preview_label.clear()
        self._preview_label.setText("No preview")

        # Hide overlays
        self._banner_overlay.hide()
        self._inplace_overlay.hide()

    def _toggle_pause(self):
        """Toggle pause state."""
        if not self._capturing:
            return
        self._paused = not self._paused
        if self._paused:
            self._pause_btn.setText("Resume")
            self._banner_overlay.hide()
            self._inplace_overlay.hide()
        else:
            self._pause_btn.setText("Pause")
            self._show_overlay()

    def _on_key_press(self, key):
        """Handle global key press (called from pynput thread)."""
        # Compare the pressed key with our hotkey
        if key == self._current_hotkey:
            self.hotkey_pressed.emit()

    def _on_pause_hotkey_changed(self, key_sequence: QKeySequence):
        """Update pause hotkey when changed in UI."""
        if key_sequence.isEmpty():
            return
        # Convert Qt key sequence to pynput key
        key_str = key_sequence.toString().lower()
        self._current_hotkey = self._qt_key_to_pynput(key_str)
        # Clear focus so it stops capturing keys
        self._pause_hotkey.clearFocus()

    def _qt_key_to_pynput(self, key_str: str):
        """Convert Qt key string to pynput key."""
        # Map common keys
        key_map = {
            "space": keyboard.Key.space,
            "esc": keyboard.Key.esc,
            "escape": keyboard.Key.esc,
            "tab": keyboard.Key.tab,
            "return": keyboard.Key.enter,
            "enter": keyboard.Key.enter,
            "f1": keyboard.Key.f1,
            "f2": keyboard.Key.f2,
            "f3": keyboard.Key.f3,
            "f4": keyboard.Key.f4,
            "f5": keyboard.Key.f5,
            "f6": keyboard.Key.f6,
            "f7": keyboard.Key.f7,
            "f8": keyboard.Key.f8,
            "f9": keyboard.Key.f9,
            "f10": keyboard.Key.f10,
            "f11": keyboard.Key.f11,
            "f12": keyboard.Key.f12,
        }
        if key_str in key_map:
            return key_map[key_str]
        # For single characters, use KeyCode
        if len(key_str) == 1:
            return keyboard.KeyCode.from_char(key_str)
        return keyboard.Key.space  # fallback

    def _on_mode_changed(self, button_id: int):
        """Handle mode selection change."""
        self._mode = "banner" if button_id == 0 else "inplace"

        self._process_worker.set_mode(self._mode)
        self._config.overlay_mode = self._mode

        if self._capturing and not self._paused:
            self._show_overlay()

    def _show_overlay(self):
        """Show the appropriate overlay."""
        if self._mode == "banner":
            self._inplace_overlay.hide()
            self._banner_overlay.show()
        else:
            self._banner_overlay.hide()
            if self._last_bounds:
                self._inplace_overlay.position_over_window(self._last_bounds)
            self._inplace_overlay.show()

    def _on_frame(self, frame, fps: float, bounds: dict):
        """Handle new frame from capture worker."""
        self._fps_label.setText(f"FPS: {fps:.1f}")
        self._last_frame = frame
        self._last_bounds = bounds

        # Update preview
        preview = frame.copy()
        preview.thumbnail((320, 240))
        data = preview.tobytes("raw", "RGB")
        qimg = QImage(data, preview.width, preview.height, preview.width * 3, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg)
        self._preview_label.setPixmap(pixmap)

        # Update inplace overlay position if window moved
        if self._mode == "inplace" and bounds and not self._paused:
            self._inplace_overlay.position_over_window(bounds)

    def _process_frame(self):
        """Process the latest frame through OCR and translation."""
        if self._paused or self._last_frame is None:
            return

        self._process_worker.process_frame(self._last_frame, self._config.ocr_confidence)

    def _on_text_ready(self, original: str, translated: str, cached: bool):
        """Handle translated text (banner mode)."""
        if not self._paused:
            self._banner_overlay.set_text(translated)

    def _on_regions_ready(self, regions: list):
        """Handle translated regions (inplace mode)."""
        if not self._paused:
            # On Windows, the overlay is positioned at client area (matching capture)
            # so no title bar offset is needed. On macOS, the overlay covers full window
            # but capture excludes title bar, so offset is still needed.
            import platform
            if platform.system() == "Windows":
                # Overlay matches capture area - no offset needed
                title_bar_offset = 0
            else:
                # Get content offset from capture (accounts for title bar cropping)
                content_offset = (0, 0)
                if self._capture:
                    content_offset = self._capture.get_content_offset()
                # Convert from pixels to points using scale factor
                from PySide6.QtWidgets import QApplication
                scale = QApplication.primaryScreen().devicePixelRatio()
                title_bar_offset = int(content_offset[1] / scale)

            self._inplace_overlay.set_regions(regions, title_bar_offset)

    # Settings handlers
    def _on_refresh_rate_changed(self, value: int):
        rate = value / 10.0
        self._config.refresh_rate = rate
        self._refresh_label.setText(f"{rate:.1f}s")
        if self._capturing:
            self._process_timer.setInterval(int(rate * 1000))

    def _on_confidence_changed(self, value: int):
        confidence = value / 100.0
        self._config.ocr_confidence = confidence
        self._confidence_label.setText(f"{confidence:.0%}")
        if self._ocr:
            self._ocr.confidence_threshold = confidence

    def _on_font_size_changed(self, value: int):
        self._config.font_size = value
        self._font_label.setText(f"{value}pt")
        self._banner_overlay.set_font_size(value)
        self._inplace_overlay.set_font_size(value)

    def _pick_font_color(self):
        color = QColorDialog.getColor()
        if color.isValid():
            hex_color = color.name()
            self._config.font_color = hex_color
            self._font_color_btn.setStyleSheet(f"background-color: {hex_color};")
            self._banner_overlay.set_colors(hex_color, self._config.background_color)
            self._inplace_overlay.set_colors(hex_color, self._config.background_color)

    def _pick_bg_color(self):
        color = QColorDialog.getColor()
        if color.isValid():
            hex_color = color.name()
            self._config.background_color = hex_color
            self._bg_color_btn.setStyleSheet(f"background-color: {hex_color};")
            self._banner_overlay.set_colors(self._config.font_color, hex_color)
            self._inplace_overlay.set_colors(self._config.font_color, hex_color)

    def get_config(self) -> Config:
        """Get the current configuration."""
        return self._config

    def cleanup(self):
        """Clean up resources before closing."""
        self._stop_capture()
        self._keyboard_listener.stop()
        self._banner_overlay.close()
        self._inplace_overlay.close()
