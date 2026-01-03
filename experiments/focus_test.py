#!/usr/bin/env python3
"""Test capture speed vs Qt timer speed when unfocused."""

import os
import sys
import time
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from PySide6.QtWidgets import QApplication, QMainWindow, QLabel, QVBoxLayout, QWidget
from PySide6.QtCore import QTimer, Qt

from interpreter.capture.macos import get_window_list, capture_window


class TestWindow(QMainWindow):
    def __init__(self, window_id: int):
        super().__init__()
        self.window_id = window_id
        self.setWindowTitle("Focus Test")
        self.setMinimumSize(500, 300)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self.timer_label = QLabel("Qt Timer FPS: --")
        self.timer_label.setStyleSheet("font-size: 20px;")
        layout.addWidget(self.timer_label)

        self.capture_label = QLabel("Capture FPS: --")
        self.capture_label.setStyleSheet("font-size: 20px;")
        layout.addWidget(self.capture_label)

        self.thread_label = QLabel("Background Thread FPS: --")
        self.thread_label.setStyleSheet("font-size: 20px;")
        layout.addWidget(self.thread_label)

        self.info_label = QLabel("Focus the fullscreen game to test...")
        layout.addWidget(self.info_label)

        # Qt Timer test - how often does Qt call us?
        self.qt_timer = QTimer()
        self.qt_timer.timeout.connect(self.on_qt_timer)
        self.qt_timer.setInterval(33)
        self.qt_timer_count = 0
        self.qt_timer_last = time.time()

        # Capture test - how fast is capture when Qt calls us?
        self.capture_count = 0
        self.capture_last = time.time()

        # Background thread test - captures independently of Qt
        self.thread_count = 0
        self.thread_last = time.time()
        self.thread_running = True
        self.thread = threading.Thread(target=self.background_capture, daemon=True)

        # Start everything
        self.qt_timer.start()
        self.thread.start()

        # Update display
        self.display_timer = QTimer()
        self.display_timer.timeout.connect(self.update_display)
        self.display_timer.setInterval(500)
        self.display_timer.start()

    def on_qt_timer(self):
        """Called by Qt timer."""
        self.qt_timer_count += 1

        # Also do a capture
        frame = capture_window(self.window_id)
        if frame:
            self.capture_count += 1

    def background_capture(self):
        """Background thread that captures independently."""
        while self.thread_running:
            frame = capture_window(self.window_id)
            if frame:
                self.thread_count += 1
            time.sleep(0.033)

    def update_display(self):
        """Update the FPS display."""
        now = time.time()

        # Qt timer FPS
        qt_elapsed = now - self.qt_timer_last
        if qt_elapsed >= 1.0:
            qt_fps = self.qt_timer_count / qt_elapsed
            self.timer_label.setText(f"Qt Timer FPS: {qt_fps:.1f}")
            self.qt_timer_count = 0
            self.qt_timer_last = now

        # Capture FPS (from Qt timer)
        cap_elapsed = now - self.capture_last
        if cap_elapsed >= 1.0:
            cap_fps = self.capture_count / cap_elapsed
            self.capture_label.setText(f"Capture FPS (via Qt): {cap_fps:.1f}")
            self.capture_count = 0
            self.capture_last = now

        # Thread FPS
        thread_elapsed = now - self.thread_last
        if thread_elapsed >= 1.0:
            thread_fps = self.thread_count / thread_elapsed
            self.thread_label.setText(f"Background Thread FPS: {thread_fps:.1f}")
            self.thread_count = 0
            self.thread_last = now

    def closeEvent(self, event):
        self.thread_running = False
        event.accept()


def main():
    windows = get_window_list()

    if len(sys.argv) < 2:
        print("Available windows:")
        for i, w in enumerate(windows):
            print(f"  {i}: {w['title'][:50]}")
        print("\nUsage: python focus_test.py <window_number>")
        return

    idx = int(sys.argv[1])
    window = windows[idx]
    print(f"Testing with: {window['title']}")
    print("\nThis shows 3 metrics:")
    print("  1. Qt Timer FPS - how often Qt fires the timer")
    print("  2. Capture FPS - captures triggered by Qt timer")
    print("  3. Background Thread FPS - captures from a separate thread")
    print("\nFocus the fullscreen game to see which one drops...")

    app = QApplication(sys.argv)
    win = TestWindow(window["id"])
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
