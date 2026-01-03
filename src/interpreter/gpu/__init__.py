"""Platform-agnostic GPU setup interface."""

import platform

# Platform detection
_system = platform.system()

# Import platform-specific implementation
if _system == "Darwin":
    from .macos import setup as _setup
elif _system == "Windows":
    from .windows import setup as _setup
elif _system == "Linux":
    from .linux import setup as _setup
else:
    # Unsupported platform - provide no-op implementation
    def _setup() -> bool:
        return False


def setup() -> bool:
    """Setup GPU libraries for the current platform.

    This should be called once at startup, before any GPU-dependent
    libraries (ctranslate2, onnxruntime) are imported.

    Returns:
        True if GPU setup succeeded, False otherwise.
    """
    return _setup()
