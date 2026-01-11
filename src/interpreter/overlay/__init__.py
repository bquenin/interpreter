"""Platform-agnostic overlay interface.

Imports the correct platform-specific overlay implementation.
- macOS: Uses macos.py (CGWindowBounds returns points)
- Windows: Uses windows.py (bounds in physical pixels, Win32 click-through)
- Linux: Uses linux.py (Qt-based, evaluating native Wayland support)
"""

import platform

_system = platform.system()

if _system == "Darwin":
    from .macos import BannerOverlay, InplaceOverlay
elif _system == "Windows":
    from .windows import BannerOverlay, InplaceOverlay
else:
    from .linux import BannerOverlay, InplaceOverlay

__all__ = ["BannerOverlay", "InplaceOverlay"]
