#!/usr/bin/env python3
"""Test if Qt timers are throttled when window is on different Space."""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from PySide6.QtWidgets import QApplication, QMainWindow, QLabel, QVBoxLayout, QWidget
from PySide6.QtCore import QTimer, Qt

from interpreter.capture.macos import get_window_list, capture_window


class TestWindow(QMainWindow):
    def __init__(self, window_id: int):
        super().__init__()
        self.window_id = window_id
        self.setWindowTitle("Qt Timer Test")
        self.setMinimumSize(400, 200)

        # UI
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self.fps_label = QLabel("FPS: --")
        self.fps_label.setStyleSheet("font-size: 24px;")
        layout.addWidget(self.fps_label)

        self.info_label = QLabel("Switch target window to fullscreen to test")
        layout.addWidget(self.info_label)

        # Capture timer - same as the real app
        self.capture_timer = QTimer()
        self.capture_timer.timeout.connect(self.on_capture)
        self.capture_timer.setInterval(33)  # ~30 FPS target

        # FPS tracking
        self.frame_count = 0
        self.last_fps_time = time.time()

        # Start
        self.capture_timer.start()

    def on_capture(self):
        """Called by timer - simulates the real capture workflow."""
        t0 = time.perf_counter()

        # Capture the window (same as real app)
        frame = capture_window(self.window_id)

        capture_ms = (time.perf_counter() - t0) * 1000

        if frame:
            self.frame_count += 1

            # Update FPS every second
            now = time.time()
            elapsed = now - self.last_fps_time
            if elapsed >= 1.0:
                fps = self.frame_count / elapsed
                self.fps_label.setText(f"FPS: {fps:.1f} (capture: {capture_ms:.0f}ms)")
                self.frame_count = 0
                self.last_fps_time = now


def main():
    windows = get_window_list()

    if len(sys.argv) < 2:
        print("Available windows:")
        for i, w in enumerate(windows):
            print(f"  {i}: {w['title'][:50]}")
        print("\nUsage: python qt_timer_test.py <window_number>")
        return

    idx = int(sys.argv[1])
    window = windows[idx]
    print(f"Testing with: {window['title']}")
    print("Switch that window to fullscreen and watch the FPS...")

    app = QApplication(sys.argv)
    win = TestWindow(window["id"])
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
