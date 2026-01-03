"""Main entry point for Interpreter.

This module is executed when running:
- python -m interpreter
- interpreter-v2 (via pyproject.toml entry point)
"""

from .gui import run

if __name__ == "__main__":
    run()
