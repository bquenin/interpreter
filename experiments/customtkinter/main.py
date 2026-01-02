#!/usr/bin/env python3
"""CustomTkinter GUI prototype for Interpreter.

Run from project root:
    python -m experiments.customtkinter.main

Or directly:
    python experiments/customtkinter/main.py
"""

import sys
from pathlib import Path

# Ensure we can import from src
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import customtkinter as ctk


def main():
    # Set appearance mode and color theme
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    # Import here to avoid circular imports
    from .gui import MainWindow

    app = MainWindow()
    app.mainloop()


if __name__ == "__main__":
    main()
