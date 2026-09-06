"""Main entry point for Interpreter.

This module is executed when running:
- python -m interpreter
- interpreter-v2 (via pyproject.toml entry point)

Both routes go through interpreter.main so that startup work such as
resolving the install location happens before the GUI is imported.
"""

from . import main

if __name__ == "__main__":
    main()
