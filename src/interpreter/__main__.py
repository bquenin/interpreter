"""Main entry point for Interpreter.

This module is executed when running:
- python -m interpreter
- interpreter-v2 (via pyproject.toml entry point)
"""

import faulthandler
import signal

# Enable faulthandler to dump thread stacks on SIGUSR1 (Unix only)
# Usage: kill -USR1 <pid>  (find pid with: pgrep -f interpreter)
if hasattr(signal, "SIGUSR1"):
    faulthandler.register(signal.SIGUSR1, all_threads=True)

from .gui import run

if __name__ == "__main__":
    run()
