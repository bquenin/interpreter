#!/usr/bin/env python3
"""wxPython GUI prototype for Interpreter.

Run from project root:
    python -m experiments.wxpython.main

Or directly:
    python experiments/wxpython/main.py
"""

import sys
from pathlib import Path

# Ensure we can import from src
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import wx


def main():
    app = wx.App()

    # Import here to avoid circular imports
    from .gui import MainWindow

    window = MainWindow()
    window.Show()

    app.MainLoop()


if __name__ == "__main__":
    main()
