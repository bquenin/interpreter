"""Platform-agnostic GPU setup interface."""

import platform

# Platform detection
_system = platform.system()

# Import platform-specific implementation
if _system == "Darwin":
    from .macos import setup as _setup, is_available as _is_available
elif _system == "Windows":
    from .windows import setup as _setup, is_available as _is_available
elif _system == "Linux":
    from .linux import setup as _setup, is_available as _is_available
else:
    # Unsupported platform - provide no-op implementations
    def _setup() -> bool:
        return False

    def _is_available() -> bool:
        return False


# Module-level state
_gpu_initialized = False
_gpu_available = False


def setup() -> bool:
    """Setup GPU libraries for the current platform.

    This should be called once at startup, before any GPU-dependent
    libraries (ctranslate2, onnxruntime) are imported.

    Returns:
        True if GPU setup succeeded, False otherwise.
    """
    global _gpu_initialized, _gpu_available

    if _gpu_initialized:
        return _gpu_available

    _gpu_available = _setup()
    _gpu_initialized = True

    return _gpu_available


def is_available() -> bool:
    """Check if GPU acceleration is available.

    Returns:
        True if GPU is available and setup succeeded.
    """
    if not _gpu_initialized:
        setup()

    return _gpu_available
