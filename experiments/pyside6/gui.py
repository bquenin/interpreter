"""PySide6 main GUI window with settings and controls."""

import sys
import time
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QPushButton, QGroupBox, QSlider,
    QSystemTrayIcon, QMenu, QApplication, QFrame
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QIcon, QAction, QPixmap, QImage

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from interpreter.capture import WindowCapture
from .overlay import BannerOverlay, InplaceOverlay


class CaptureWorker(QObject):
    """Worker for capture in main thread with timer."""
    frame_ready = Signal(object, float)  # PIL Image, fps

    def __init__(self):
        super().__init__()
        self.capture: Optional[WindowCapture] = None
        self._last_frame_time = 0
        self._frame_count = 0
        self._fps = 0.0
        self._fps_update_time = 0

    def set_capture(self, capture: Optional[WindowCapture]):
        self.capture = capture
        self._frame_count = 0
        self._fps = 0.0
        self._fps_update_time = time.time()

    def fetch_frame(self):
        """Fetch a frame - called by timer."""
        if self.capture is None:
            return

        frame = self.capture.get_frame()
        if frame is not None:
            self._frame_count += 1
            now = time.time()
            elapsed = now - self._fps_update_time
            if elapsed >= 1.0:
                self._fps = self._frame_count / elapsed
                self._frame_count = 0
                self._fps_update_time = now

            self.frame_ready.emit(frame, self._fps)


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Interpreter - PySide6 Prototype")
        self.setMinimumSize(500, 400)

        # State
        self._capturing = False
        self._mode = "banner"  # or "inplace"
        self._windows_list: list[dict] = []

        # Components
        self._capture: Optional[WindowCapture] = None
        self._worker = CaptureWorker()
        self._worker.frame_ready.connect(self._on_frame)

        self._banner_overlay = BannerOverlay()
        self._inplace_overlay = InplaceOverlay()

        # Timer for capture polling
        self._capture_timer = QTimer()
        self._capture_timer.timeout.connect(self._worker.fetch_frame)
        self._capture_timer.setInterval(33)  # ~30 FPS

        self._setup_ui()
        self._setup_tray()
        self._refresh_windows()

    def _setup_ui(self):
        """Set up the main UI."""
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # Window Selection
        window_group = QGroupBox("Window Selection")
        window_layout = QHBoxLayout(window_group)

        self._window_combo = QComboBox()
        self._window_combo.setMinimumWidth(300)
        window_layout.addWidget(self._window_combo)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_windows)
        window_layout.addWidget(refresh_btn)

        layout.addWidget(window_group)

        # Controls
        controls_group = QGroupBox("Controls")
        controls_layout = QHBoxLayout(controls_group)

        self._start_btn = QPushButton("Start Capture")
        self._start_btn.clicked.connect(self._toggle_capture)
        controls_layout.addWidget(self._start_btn)

        self._mode_btn = QPushButton("Mode: Banner")
        self._mode_btn.clicked.connect(self._toggle_mode)
        controls_layout.addWidget(self._mode_btn)

        layout.addWidget(controls_group)

        # Status
        status_group = QGroupBox("Status")
        status_layout = QVBoxLayout(status_group)

        self._status_label = QLabel("Status: Idle")
        status_layout.addWidget(self._status_label)

        self._fps_label = QLabel("FPS: --")
        status_layout.addWidget(self._fps_label)

        # Preview frame
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

    def _setup_tray(self):
        """Set up system tray icon."""
        self._tray = QSystemTrayIcon(self)

        # Create a simple icon (colored square)
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.darkCyan)
        self._tray.setIcon(QIcon(pixmap))

        # Tray menu
        menu = QMenu()

        show_action = QAction("Show", self)
        show_action.triggered.connect(self.show)
        menu.addAction(show_action)

        toggle_action = QAction("Toggle Capture", self)
        toggle_action.triggered.connect(self._toggle_capture)
        menu.addAction(toggle_action)

        menu.addSeparator()

        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(QApplication.quit)
        menu.addAction(quit_action)

        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _on_tray_activated(self, reason):
        """Handle tray icon click."""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self.show()
                self.raise_()

    def _refresh_windows(self):
        """Refresh the window list."""
        self._windows_list = WindowCapture.list_windows()
        self._window_combo.clear()
        for win in self._windows_list:
            title = win.get("title", "Unknown")
            if len(title) > 50:
                title = title[:50] + "..."
            self._window_combo.addItem(title)

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

        self._capture = WindowCapture(title)
        if not self._capture.find_window():
            self._status_label.setText(f"Status: Window not found")
            return

        if not self._capture.start_stream():
            self._status_label.setText(f"Status: Failed to start stream")
            return

        self._worker.set_capture(self._capture)
        self._capture_timer.start()

        self._capturing = True
        self._start_btn.setText("Stop Capture")
        self._status_label.setText(f"Status: Capturing '{title[:30]}...'")

        # Show overlay
        self._show_overlay()

    def _stop_capture(self):
        """Stop capturing."""
        self._capture_timer.stop()
        if self._capture:
            self._capture.stop_stream()
            self._capture = None
        self._worker.set_capture(None)

        self._capturing = False
        self._start_btn.setText("Start Capture")
        self._status_label.setText("Status: Idle")
        self._fps_label.setText("FPS: --")

        # Hide overlays
        self._banner_overlay.hide()
        self._inplace_overlay.hide()

    def _toggle_mode(self):
        """Toggle between banner and inplace mode."""
        if self._mode == "banner":
            self._mode = "inplace"
            self._mode_btn.setText("Mode: Inplace")
        else:
            self._mode = "banner"
            self._mode_btn.setText("Mode: Banner")

        if self._capturing:
            self._show_overlay()

    def _show_overlay(self):
        """Show the appropriate overlay."""
        if self._mode == "banner":
            self._inplace_overlay.hide()
            self._banner_overlay.show()
        else:
            self._banner_overlay.hide()
            if self._capture and self._capture.bounds:
                self._inplace_overlay.position_over_window(self._capture.bounds)
            self._inplace_overlay.show()

    def _on_frame(self, frame, fps: float):
        """Handle new frame from capture."""
        self._fps_label.setText(f"FPS: {fps:.1f}")

        # Update preview (scale down)
        preview = frame.copy()
        preview.thumbnail((320, 240))

        # Convert PIL to QPixmap
        data = preview.tobytes("raw", "RGB")
        qimg = QImage(data, preview.width, preview.height, preview.width * 3, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg)
        self._preview_label.setPixmap(pixmap)

        # Update overlay
        if self._mode == "banner":
            self._banner_overlay.set_text(f"Capturing... Frame at {fps:.1f} FPS")
        else:
            # Update inplace position if window moved
            if self._capture and self._capture.bounds:
                self._inplace_overlay.position_over_window(self._capture.bounds)
            # Sample regions for demo
            self._inplace_overlay.set_regions([
                {"text": "Sample text 1", "x": 50, "y": 50},
                {"text": "Another region", "x": 100, "y": 150},
            ])

    def closeEvent(self, event):
        """Handle window close - minimize to tray instead."""
        event.ignore()
        self.hide()
        self._tray.showMessage(
            "Interpreter",
            "Running in background. Click tray icon to show.",
            QSystemTrayIcon.MessageIcon.Information,
            2000
        )
