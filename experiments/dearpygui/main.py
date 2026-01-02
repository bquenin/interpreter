#!/usr/bin/env python3
"""Dear PyGui GUI prototype for Interpreter.

Run from project root:
    python -m experiments.dearpygui.main

Or directly:
    python experiments/dearpygui/main.py

NOTE: Dear PyGui has significant limitations for this use case:
- Cannot create transparent windows
- Cannot make windows click-through
- No system tray support

It's excellent for settings GUIs and real-time displays, but the overlay
functionality would need a separate library (Qt/tkinter).
"""

import sys
from pathlib import Path

# Ensure we can import from src
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


def main():
    # Import here to avoid import issues
    from .gui import MainGUI

    app = MainGUI()
    app.setup()
    app.run()


if __name__ == "__main__":
    main()
