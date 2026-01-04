"""PySide6 GUI module for Interpreter.

This module provides the graphical user interface including:
- Main settings window
- Banner and inplace overlay windows
- Background workers for capture, OCR, and translation
"""

from .app import run

__all__ = ["run"]
