#!/usr/bin/env python3
"""PySide6 GUI prototype for Interpreter.

Run from project root:
    python -m experiments.pyside6.main

Or directly:
    python experiments/pyside6/main.py
"""

import sys
from pathlib import Path

# Ensure we can import from src
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt


def main():
    # Enable high DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Interpreter")
    app.setQuitOnLastWindowClosed(False)  # Keep running in tray

    # Import here to avoid circular imports
    from .gui import MainWindow

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
