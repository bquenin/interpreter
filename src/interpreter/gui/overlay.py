"""Platform-agnostic overlay interface.

Imports the correct platform-specific overlay implementation.
- macOS: Uses overlay_macos.py (CGWindowBounds returns points)
- Windows: Uses overlay_windows.py (bounds in physical pixels, Win32 click-through)
- Linux: Uses overlay_linux.py (Tkinter-based for better X11/Wayland compatibility)
"""

import platform

_system = platform.system()

if _system == "Darwin":
    from .overlay_macos import BannerOverlay, InplaceOverlay
elif _system == "Windows":
    from .overlay_windows import BannerOverlay, InplaceOverlay
else:
    from .overlay_linux import BannerOverlay, InplaceOverlay

__all__ = ["BannerOverlay", "InplaceOverlay"]
