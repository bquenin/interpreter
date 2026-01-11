"""Main application window with settings and controls."""

import os

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QImage, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QColorDialog,
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QMainWindow,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .. import log
from ..capture import Capture, WindowCapture
from ..capture.convert import bgra_to_rgb_pil
from ..config import Config
from ..overlay import BannerOverlay, InplaceOverlay
from ..permissions import (
    check_accessibility,
    check_screen_recording,
    is_macos,
    open_accessibility_settings,
    open_screen_recording_settings,
    request_accessibility,
    request_screen_recording,
)
from . import keyboard
from .workers import ProcessWorker

logger = log.get_logger()

# Font settings
FONT_FAMILY = "Helvetica"
MIN_FONT_SIZE = 8
MAX_FONT_SIZE = 72

# Fixed processing interval (2 FPS)
PROCESS_INTERVAL_MS = 500


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
        # Detect session type: Wayland or X11-only
        self._is_wayland_session = bool(os.environ.get("WAYLAND_DISPLAY"))
        self._wayland_portal = None  # WaylandPortalCapture instance (for managing portal session lifecycle)
        self._wayland_selecting = False  # Guard against re-entry during portal flow
        self._fixing_ocr = False  # Track if we're re-downloading OCR model
        self._fixing_translation = False  # Track if we're re-downloading translation model

        # Components - unified capture interface (WindowCapture or WaylandCaptureStream)
        self._capture: Capture | None = None

        # Worker for OCR/translation (uses Python threading internally)
        self._process_worker = ProcessWorker()
        self._process_worker.text_ready.connect(self._on_text_ready)
        self._process_worker.regions_ready.connect(self._on_regions_ready)
        self._process_worker.models_ready.connect(self._on_models_ready)
        self._process_worker.models_failed.connect(self._on_models_failed)
        self._process_worker.ocr_status.connect(self._on_ocr_status)
        self._process_worker.translation_status.connect(self._on_translation_status)

        # Overlays
        self._banner_overlay = BannerOverlay(
            font_family=FONT_FAMILY,
            font_size=config.font_size,
            font_color=config.font_color,
            background_color=config.background_color,
        )
        self._inplace_overlay = InplaceOverlay(
            font_family=FONT_FAMILY,
            font_size=config.font_size,
            font_color=config.font_color,
            background_color=config.background_color,
        )

        # Apply saved banner position if available
        if config.banner_x is not None and config.banner_y is not None:
            logger.debug("restoring banner position", x=config.banner_x, y=config.banner_y)
            self._banner_overlay.set_position(config.banner_x, config.banner_y)

        # Main processing timer (fixed 2 FPS)
        self._process_timer = QTimer()
        self._process_timer.timeout.connect(self._capture_and_process)
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

        # Models Section
        models_group = QGroupBox("Models")
        models_layout = QGridLayout(models_group)

        # OCR model row
        models_layout.addWidget(QLabel("OCR:"), 0, 0)
        models_layout.addWidget(QLabel("MeikiOCR"), 0, 1)
        self._ocr_status_label = QLabel("Loading...")
        models_layout.addWidget(self._ocr_status_label, 0, 2)

        # Translation model row
        models_layout.addWidget(QLabel("Translation:"), 1, 0)
        models_layout.addWidget(QLabel("Sugoi V4"), 1, 1)
        self._translation_status_label = QLabel("Loading...")
        models_layout.addWidget(self._translation_status_label, 1, 2)

        # Fix Models button (hidden by default)
        self._fix_models_btn = QPushButton("Fix Models")
        self._fix_models_btn.clicked.connect(self._on_fix_models)
        self._fix_models_btn.setVisible(False)
        models_layout.addWidget(self._fix_models_btn, 2, 0, 1, 3, Qt.AlignRight)

        # Set column stretch so status is right-aligned
        models_layout.setColumnStretch(1, 1)

        layout.addWidget(models_group)

        # macOS Permissions Section (only shown on macOS)
        if is_macos():
            self._setup_permissions_ui(layout)

        # Window Selection
        window_group = QGroupBox("Window Selection")
        window_layout = QHBoxLayout(window_group)

        if self._is_wayland_session:
            # Wayland: single toggle button for capture
            self._select_window_btn = QPushButton("Start Capture")
            self._select_window_btn.setEnabled(False)  # Disabled until models are loaded
            self._select_window_btn.clicked.connect(self._toggle_wayland_capture)
            window_layout.addWidget(self._select_window_btn, 1)

            # Not used in Wayland mode
            self._window_combo = None
            self._start_btn = None
            self._stop_btn = None
        else:
            # X11: dropdown + start/refresh buttons
            self._window_combo = QComboBox()
            self._window_combo.setMinimumWidth(250)
            self._window_combo.activated.connect(self._on_window_selected)
            window_layout.addWidget(self._window_combo, 1)

            self._start_btn = QPushButton("Start Capture")
            self._start_btn.setEnabled(False)  # Disabled until models are loaded
            self._start_btn.clicked.connect(self._toggle_capture)
            window_layout.addWidget(self._start_btn)

            refresh_btn = QPushButton("Refresh List")
            refresh_btn.clicked.connect(self._refresh_windows)
            window_layout.addWidget(refresh_btn)

            # Not used in X11 mode
            self._select_window_btn = None
            self._stop_btn = None

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
        self._banner_btn.setStyleSheet(
            segment_style + "QPushButton { border-radius: 4px 0 0 4px; border-right: none; }"
        )
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

        self._pause_btn = QPushButton("Hide")
        self._pause_btn.clicked.connect(self._toggle_pause)
        self._pause_btn.setEnabled(False)
        overlay_layout.addWidget(self._pause_btn)

        # Hotkey picker for pause - load from config
        hotkey_str = self._config.hotkeys.get("toggle_overlay", "space")
        self._pause_hotkey = QKeySequenceEdit(self._hotkey_str_to_qkeysequence(hotkey_str))
        self._pause_hotkey.setFixedWidth(80)
        self._pause_hotkey.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._pause_hotkey.keySequenceChanged.connect(self._on_pause_hotkey_changed)
        overlay_layout.addWidget(self._pause_hotkey)

        # Global hotkey listener - load from config
        self._current_hotkey = self._qt_key_to_key(hotkey_str)
        self._keyboard_listener = keyboard.Listener(on_press=self._on_key_press)
        self._keyboard_listener.start()
        self.hotkey_pressed.connect(self._toggle_pause)

        layout.addWidget(overlay_group)

        # Settings
        settings_group = QGroupBox("Settings")
        settings_layout = QGridLayout(settings_group)

        # OCR Confidence
        settings_layout.addWidget(QLabel("OCR Confidence:"), 0, 0)
        self._confidence_slider = QSlider(Qt.Orientation.Horizontal)
        self._confidence_slider.setRange(0, 100)
        self._confidence_slider.setValue(int(self._config.ocr_confidence * 100))
        self._confidence_slider.valueChanged.connect(self._on_confidence_changed)
        settings_layout.addWidget(self._confidence_slider, 0, 1)
        self._confidence_label = QLabel(f"{self._config.ocr_confidence:.0%}")
        settings_layout.addWidget(self._confidence_label, 0, 2)

        # Font size
        settings_layout.addWidget(QLabel("Font Size:"), 1, 0)
        self._font_slider = QSlider(Qt.Orientation.Horizontal)
        self._font_slider.setRange(MIN_FONT_SIZE, MAX_FONT_SIZE)
        self._font_slider.setValue(self._config.font_size)
        self._font_slider.valueChanged.connect(self._on_font_size_changed)
        settings_layout.addWidget(self._font_slider, 1, 1)
        self._font_label = QLabel(f"{self._config.font_size}pt")
        settings_layout.addWidget(self._font_label, 1, 2)

        # Colors
        settings_layout.addWidget(QLabel("Font Color:"), 2, 0)
        self._font_color_btn = QPushButton()
        self._font_color_btn.setStyleSheet(f"background-color: {self._config.font_color};")
        self._font_color_btn.clicked.connect(self._pick_font_color)
        settings_layout.addWidget(self._font_color_btn, 2, 1)

        settings_layout.addWidget(QLabel("Background:"), 3, 0)
        self._bg_color_btn = QPushButton()
        self._bg_color_btn.setStyleSheet(f"background-color: {self._config.background_color};")
        self._bg_color_btn.clicked.connect(self._pick_bg_color)
        settings_layout.addWidget(self._bg_color_btn, 3, 1)

        layout.addWidget(settings_group)

        # Preview
        preview_group = QGroupBox("Preview")
        preview_layout = QVBoxLayout(preview_group)

        self._preview_label = QLabel()
        self._preview_label.setFixedSize(320, 240)
        self._preview_label.setFrameStyle(QFrame.Shape.Box)
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setText("No preview")
        self._preview_label.setStyleSheet("background-color: #2a2a2a; color: #888;")
        preview_layout.addWidget(self._preview_label)

        layout.addWidget(preview_group)

        # Stretch at bottom
        layout.addStretch()

        # Status bar
        self.statusBar().showMessage("Idle")

    def _setup_permissions_ui(self, layout: QVBoxLayout):
        """Set up macOS permissions section."""
        permissions_group = QGroupBox("macOS Permissions")
        permissions_layout = QGridLayout(permissions_group)

        # Screen Recording row
        permissions_layout.addWidget(QLabel("Screen Recording"), 0, 0)
        self._screen_recording_status = QLabel()
        permissions_layout.addWidget(self._screen_recording_status, 0, 1)
        self._screen_recording_btn = QPushButton("Grant")
        self._screen_recording_btn.setFixedWidth(80)
        self._screen_recording_btn.clicked.connect(self._on_request_screen_recording)
        permissions_layout.addWidget(self._screen_recording_btn, 0, 2)

        # Accessibility row (required for global hotkeys)
        permissions_layout.addWidget(QLabel("Accessibility"), 1, 0)
        self._accessibility_status = QLabel()
        permissions_layout.addWidget(self._accessibility_status, 1, 1)
        self._accessibility_btn = QPushButton("Grant")
        self._accessibility_btn.setFixedWidth(80)
        self._accessibility_btn.clicked.connect(self._on_request_accessibility)
        permissions_layout.addWidget(self._accessibility_btn, 1, 2)

        # Set column stretch
        permissions_layout.setColumnStretch(0, 1)

        layout.addWidget(permissions_group)

        # Initial permission check
        self._update_permissions_status()

    def _update_permissions_status(self):
        """Update the permission status indicators."""
        if not is_macos():
            return

        # Screen Recording
        if check_screen_recording():
            self._screen_recording_status.setText("✓ Granted")
            self._screen_recording_status.setStyleSheet("color: green;")
            self._screen_recording_btn.setVisible(False)
        else:
            self._screen_recording_status.setText("✗ Required")
            self._screen_recording_status.setStyleSheet("color: red;")
            self._screen_recording_btn.setVisible(True)

        # Accessibility
        if check_accessibility():
            self._accessibility_status.setText("✓ Granted")
            self._accessibility_status.setStyleSheet("color: green;")
            self._accessibility_btn.setVisible(False)
        else:
            self._accessibility_status.setText("✗ Required")
            self._accessibility_status.setStyleSheet("color: red;")
            self._accessibility_btn.setVisible(True)

    def _on_request_screen_recording(self):
        """Handle Screen Recording grant button click."""
        # Try to request permission (triggers system dialog if first time)
        if not request_screen_recording():
            # Already denied, open System Settings
            open_screen_recording_settings()

        # Update status after a short delay (permission may take a moment to register)
        QTimer.singleShot(500, self._update_permissions_status)

    def _on_request_accessibility(self):
        """Handle Accessibility grant button click."""
        # Try to request permission (triggers system dialog)
        if not request_accessibility():
            # Already denied, open System Settings
            open_accessibility_settings()

        # Update status after a short delay
        QTimer.singleShot(500, self._update_permissions_status)

    def _load_models(self):
        """Start worker thread and load OCR/translation models."""
        self.statusBar().showMessage("Loading models...")
        self._process_worker.set_mode(self._mode)
        self._process_worker.start(self._config.ocr_confidence)

    def _on_models_ready(self):
        """Handle models loaded signal from worker thread."""
        # Enable the appropriate capture button
        if self._start_btn:
            self._start_btn.setEnabled(True)
        if self._select_window_btn:
            self._select_window_btn.setEnabled(True)
        self.statusBar().showMessage("Ready")
        logger.debug("models loaded")

    def _on_models_failed(self, error: str):
        """Handle model loading failure from worker thread."""
        # Disable the appropriate capture button
        if self._start_btn:
            self._start_btn.setEnabled(False)
        if self._select_window_btn:
            self._select_window_btn.setEnabled(False)
        self._fix_models_btn.setVisible(True)
        self.statusBar().showMessage(f"Model loading failed: {error[:100]}")
        logger.error("model loading failed", error=error)

    def _on_ocr_status(self, status: str):
        """Handle OCR model status change."""
        # Show "Downloading..." instead of "Loading..." when fixing
        if status == "loading" and self._fixing_ocr:
            status = "downloading"
        if status == "ready":
            self._fixing_ocr = False
        self._update_status_label(self._ocr_status_label, status)
        self._update_fix_button_visibility()

    def _on_translation_status(self, status: str):
        """Handle translation model status change."""
        # Show "Downloading..." instead of "Loading..." when fixing
        if status == "loading" and self._fixing_translation:
            status = "downloading"
        if status == "ready":
            self._fixing_translation = False
        self._update_status_label(self._translation_status_label, status)
        self._update_fix_button_visibility()

    def _update_status_label(self, label: QLabel, status: str):
        """Update a model status label with appropriate text and style."""
        if status == "loading":
            label.setText("Loading...")
            label.setStyleSheet("")
        elif status == "downloading":
            label.setText("Downloading...")
            label.setStyleSheet("")
        elif status == "ready":
            label.setText("Ready")
            label.setStyleSheet("color: green;")
        elif status == "error":
            label.setText("Error")
            label.setStyleSheet("color: red;")

    def _update_fix_button_visibility(self):
        """Show/hide the Fix Models button based on model status."""
        has_error = self._ocr_status_label.text() == "Error" or self._translation_status_label.text() == "Error"
        self._fix_models_btn.setVisible(has_error)

    def _on_fix_models(self):
        """Handle Fix Models button click."""
        from ..models import delete_model_cache

        # Track which models we're fixing (to show "Downloading..." instead of "Loading...")
        self._fixing_ocr = False
        self._fixing_translation = False

        # Delete caches for failed models
        failed = self._process_worker.get_failed_models()
        if "ocr" in failed:
            delete_model_cache("rtr46/meiki.text.detect.v0")
            delete_model_cache("rtr46/meiki.txt.recognition.v0")
            self._fixing_ocr = True
        if "translation" in failed:
            delete_model_cache("entai2965/sugoi-v4-ja-en-ctranslate2")
            self._fixing_translation = True

        # Hide the button while fixing
        self._fix_models_btn.setVisible(False)
        self.statusBar().showMessage("Downloading models...")

        # Stop and restart the worker to reload models
        self._process_worker.stop()
        self._process_worker = ProcessWorker()
        self._process_worker.text_ready.connect(self._on_text_ready)
        self._process_worker.regions_ready.connect(self._on_regions_ready)
        self._process_worker.models_ready.connect(self._on_models_ready)
        self._process_worker.models_failed.connect(self._on_models_failed)
        self._process_worker.ocr_status.connect(self._on_ocr_status)
        self._process_worker.translation_status.connect(self._on_translation_status)
        self._process_worker.set_mode(self._mode)
        self._process_worker.start(self._config.ocr_confidence)

    def _refresh_windows(self):
        """Refresh the window list (X11 only)."""
        if self._is_wayland_session or self._window_combo is None:
            return

        self._window_combo.clear()
        self._windows_list = WindowCapture.list_windows()
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
        # Wayland session: always use portal capture
        if self._is_wayland_session:
            self._start_wayland_capture()
            return

        # X11 session: use selected window from list
        idx = self._window_combo.currentIndex()
        if idx < 0 or idx >= len(self._windows_list):
            self.statusBar().showMessage("No window selected")
            return

        window = self._windows_list[idx]
        title = window.get("title", "")
        window_id = window.get("id")
        bounds = window.get("bounds")

        self._capture = WindowCapture(title, window_id=window_id, bounds=bounds)
        if not self._capture.find_window():
            self.statusBar().showMessage("Window not found")
            return

        try:
            if not self._capture.start_stream():
                self.statusBar().showMessage("Failed to start stream")
                return
        except Exception as e:
            error_msg = str(e)
            log.get_logger().error("capture failed", error=error_msg)
            # Show truncated message in status bar (full message in logs)
            display_msg = error_msg.split("\n")[0][:100]  # First line, max 100 chars
            self.statusBar().showMessage(f"Capture failed: {display_msg}")
            self._capture = None
            return

        # Start single timer for capture + processing (fixed 2 FPS)
        self._process_timer.setInterval(PROCESS_INTERVAL_MS)
        self._process_timer.start()

        self._capturing = True
        self._paused = False
        if self._start_btn:
            self._start_btn.setText("Stop Capture")
        self._pause_btn.setEnabled(True)
        self._pause_btn.setText("Hide")
        self.statusBar().showMessage(f"Capturing '{title[:40]}...'")

        # Update config with selected window
        self._config.window_title = title

        # Show overlay
        self._show_overlay()

    def _on_window_selected(self, index: int):
        """Handle window selection change (X11 only)."""
        # Not used in Wayland mode
        pass

    def _toggle_wayland_capture(self):
        """Toggle Wayland capture on/off."""
        if self._capturing:
            self._stop_capture()
        else:
            self._start_wayland_capture()

    def _start_wayland_capture(self):
        """Start Wayland capture using xdg-desktop-portal."""
        from ..capture.linux_wayland import WaylandCaptureStream, WaylandPortalCapture

        # Guard against re-entry (portal releases GIL, allowing Qt events to process)
        if self._wayland_selecting:
            return
        self._wayland_selecting = True

        self.statusBar().showMessage("Select a window...")
        if self._select_window_btn:
            self._select_window_btn.setEnabled(False)

        try:
            self._wayland_portal = WaylandPortalCapture()

            # Synchronous API (pipewire-capture 0.2.0) - returns stream info directly
            stream_info = self._wayland_portal.select_window()
            self._wayland_selecting = False

            if not stream_info:
                self.statusBar().showMessage("Window selection cancelled")
                if self._select_window_btn:
                    self._select_window_btn.setEnabled(True)
                self._wayland_portal.close()
                self._wayland_portal = None
                return

            fd, node_id, width, height = stream_info

            # Use unified capture interface
            self._capture = WaylandCaptureStream(fd, node_id, width, height)
            self._capture.start()

            # Start processing timer
            self._process_timer.setInterval(PROCESS_INTERVAL_MS)
            self._process_timer.start()

            self._capturing = True
            self._paused = False
            self._pause_btn.setEnabled(True)
            self._pause_btn.setText("Hide")
            self.statusBar().showMessage("Capturing Wayland window...")

            # Update button to show stop action
            if self._select_window_btn:
                self._select_window_btn.setText("Stop Capture")
                self._select_window_btn.setEnabled(True)

            # Show overlay
            self._show_overlay()

        except Exception as e:
            logger.error("failed to start wayland capture", error=str(e))
            self.statusBar().showMessage("Wayland capture failed")
            if self._select_window_btn:
                self._select_window_btn.setEnabled(True)
            self._wayland_selecting = False
            if self._wayland_portal:
                self._wayland_portal.close()
                self._wayland_portal = None

    def _stop_capture(self):
        """Stop capturing."""
        self._process_timer.stop()

        # Stop capture using unified interface
        if self._capture:
            self._capture.stop()
            self._capture = None

        # Close Wayland portal session if active
        if self._wayland_portal:
            self._wayland_portal.close()
            self._wayland_portal = None

        self._capturing = False
        self._paused = False
        self._pause_btn.setEnabled(False)
        self.statusBar().showMessage("Ready")

        # Update UI based on session type
        if self._is_wayland_session:
            if self._select_window_btn:
                self._select_window_btn.setText("Start Capture")
                self._select_window_btn.setEnabled(True)
        else:
            if self._start_btn:
                self._start_btn.setText("Start Capture")

        # Clear preview
        self._preview_label.clear()
        self._preview_label.setText("No preview")

        # Hide overlays and clear inplace labels
        self._banner_overlay.hide()
        self._inplace_overlay.clear_regions()
        self._inplace_overlay.hide()

    def _toggle_pause(self):
        """Toggle pause state."""
        if not self._capturing:
            return
        self._paused = not self._paused
        if self._paused:
            self._pause_btn.setText("Show")
            self._banner_overlay.hide()
            self._inplace_overlay.clear_regions()
            self._inplace_overlay.hide()
        else:
            self._pause_btn.setText("Hide")
            self._show_overlay()

    def _on_key_press(self, key):
        """Handle global key press (called from keyboard listener thread)."""
        # Compare the pressed key with our hotkey
        logger.debug("hotkey check", pressed=key, hotkey=self._current_hotkey, match=(key == self._current_hotkey))
        if key == self._current_hotkey:
            self.hotkey_pressed.emit()

    def _on_pause_hotkey_changed(self, key_sequence: QKeySequence):
        """Update pause hotkey when changed in UI."""
        if key_sequence.isEmpty():
            return
        # Convert Qt key sequence to keyboard key
        key_str = key_sequence.toString().lower()
        self._current_hotkey = self._qt_key_to_key(key_str)
        # Save to config
        self._config.hotkeys["toggle_overlay"] = key_str
        # Clear focus so it stops capturing keys
        self._pause_hotkey.clearFocus()

    def _qt_key_to_key(self, key_str: str):
        """Convert Qt key string to keyboard module key."""
        # Map common keys
        key_map = {
            "space": keyboard.Key.space,
            "esc": keyboard.Key.esc,
            "escape": keyboard.Key.esc,
            "tab": keyboard.Key.tab,
            "return": keyboard.Key.enter,
            "enter": keyboard.Key.enter,
            "backspace": keyboard.Key.backspace,
            "delete": keyboard.Key.delete,
            "home": keyboard.Key.home,
            "end": keyboard.Key.end,
            "pgup": keyboard.Key.page_up,
            "pgdown": keyboard.Key.page_down,
            "up": keyboard.Key.up,
            "down": keyboard.Key.down,
            "left": keyboard.Key.left,
            "right": keyboard.Key.right,
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

    def _hotkey_str_to_qkeysequence(self, key_str: str) -> QKeySequence:
        """Convert config hotkey string to QKeySequence for the picker widget."""
        # Map config strings to Qt key names
        key_map = {
            "space": "Space",
            "esc": "Escape",
            "escape": "Escape",
            "tab": "Tab",
            "return": "Return",
            "enter": "Return",
            "backspace": "Backspace",
            "delete": "Delete",
            "home": "Home",
            "end": "End",
            "pgup": "PgUp",
            "pgdown": "PgDown",
            "up": "Up",
            "down": "Down",
            "left": "Left",
            "right": "Right",
        }
        # Check special keys first
        if key_str.lower() in key_map:
            return QKeySequence(key_map[key_str.lower()])
        # F-keys (f1-f12)
        if key_str.lower().startswith("f") and key_str[1:].isdigit():
            return QKeySequence(key_str.upper())
        # Single character
        if len(key_str) == 1:
            return QKeySequence(key_str.upper())
        # Fallback to space
        return QKeySequence(Qt.Key.Key_Space)

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

    def _capture_and_process(self):
        """Capture a frame and process it through OCR and translation."""
        if not self._capture:
            return

        # Get frame using unified capture interface
        frame = self._capture.get_frame()

        # Check if window was closed
        if self._capture.window_invalid:
            logger.info("window closed, stopping capture")
            self._stop_capture()
            return

        # Get bounds (None on Wayland, dict on X11/Windows/macOS)
        bounds = self._capture.bounds or {}

        if frame is None:
            return

        self._last_frame = frame
        self._last_bounds = bounds

        # Update preview (convert BGRA numpy to PIL RGB for thumbnail)
        preview = bgra_to_rgb_pil(frame)
        preview.thumbnail((320, 240))
        data = preview.tobytes("raw", "RGB")
        qimg = QImage(data, preview.width, preview.height, preview.width * 3, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg)
        self._preview_label.setPixmap(pixmap)

        # Update inplace overlay position if window moved (X11 only - Wayland doesn't have bounds)
        if self._mode == "inplace" and bounds and not self._paused:
            self._inplace_overlay.position_over_window(bounds)

        # Process through OCR and translation (on worker thread)
        if not self._paused:
            self._process_worker.submit_frame(frame)

    def _on_text_ready(self, translated: str):
        """Handle translated text (banner mode)."""
        if not self._paused:
            self._banner_overlay.set_text(translated)

    def _on_regions_ready(self, regions: list):
        """Handle translated regions (inplace mode)."""
        if not self._paused:
            # Get content offset from capture (accounts for window decorations)
            content_offset = (0, 0)
            if self._capture:
                content_offset = self._capture.get_content_offset()
            self._inplace_overlay.set_regions(regions, content_offset)

    # Settings handlers
    def _on_confidence_changed(self, value: int):
        confidence = value / 100.0
        self._config.ocr_confidence = confidence
        self._confidence_label.setText(f"{confidence:.0%}")
        self._process_worker.set_confidence_threshold(confidence)

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

    def get_banner_position(self) -> tuple[int, int]:
        """Get current banner overlay position."""
        return self._banner_overlay.get_position()

    def cleanup(self):
        """Clean up resources before closing."""
        self._stop_capture()
        self._keyboard_listener.stop()
        self._process_worker.stop()
        self._banner_overlay.close()
        self._inplace_overlay.close()
