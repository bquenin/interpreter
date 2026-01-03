"""Platform-agnostic overlay interface.

Imports the correct platform-specific overlay implementation.
- macOS: Uses overlay_macos.py (CGWindowBounds returns points)
- Windows: Uses overlay_windows.py (bounds in physical pixels, Win32 click-through)
- Linux: Uses overlay_linux.py (Tkinter-based) or overlay_linux_qt.py (Qt fallback)
"""

import platform

_system = platform.system()

if _system == "Darwin":
    from .overlay_macos import BannerOverlay, InplaceOverlay
elif _system == "Windows":
    from .overlay_windows import BannerOverlay, InplaceOverlay
else:
    # Linux: try Tkinter first (better overlay behavior), fall back to Qt
    try:
        import tkinter  # noqa: F401 - just checking availability
        from .overlay_linux import BannerOverlay, InplaceOverlay
    except ImportError:
        # Tkinter not available (common in uv-managed Python)
        # Fall back to Qt-based overlay
        from .overlay_linux_qt import BannerOverlay, InplaceOverlay

__all__ = ["BannerOverlay", "InplaceOverlay"]
