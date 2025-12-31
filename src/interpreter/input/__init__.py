"""Platform-agnostic keyboard input interface."""

import platform
from typing import Callable

# Import platform-specific implementation
_system = platform.system()

if _system == "Darwin":
    from .macos import KeyboardListener
elif _system == "Windows":
    from .windows import KeyboardListener
elif _system == "Linux":
    from .linux import KeyboardListener
else:
    raise RuntimeError(f"Unsupported platform: {_system}")

__all__ = ["KeyboardListener"]
