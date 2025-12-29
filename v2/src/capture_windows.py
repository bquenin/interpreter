"""Windows-specific window capture using pygetwindow.

Note: This module is a placeholder for Windows support.
Currently untested - will be implemented when testing on Windows.
"""

from typing import Optional

from PIL import Image

# Windows-specific imports (only available on Windows)
try:
    import pygetwindow as gw
    import mss
    WINDOWS_AVAILABLE = True
except ImportError:
    WINDOWS_AVAILABLE = False


def get_window_list() -> list[dict]:
    """Get list of all windows with their properties.

    Returns:
        List of window dictionaries with keys: id, title, bounds
    """
    if not WINDOWS_AVAILABLE:
        return []

    windows = []
    for win in gw.getAllWindows():
        if win.title:  # Skip windows without titles
            windows.append({
                "id": win._hWnd,
                "title": win.title,
                "owner": "",
                "bounds": {
                    "x": win.left,
                    "y": win.top,
                    "width": win.width,
                    "height": win.height,
                }
            })
    return windows


def find_window_by_title(title_substring: str) -> Optional[dict]:
    """Find a window by partial title match.

    Args:
        title_substring: Substring to search for in window titles.

    Returns:
        Window dictionary if found, None otherwise.
    """
    title_lower = title_substring.lower()
    windows = get_window_list()

    for window in windows:
        if title_lower in window["title"].lower():
            return window

    return None


def capture_window(window_id: int) -> Optional[Image.Image]:
    """Capture a screenshot of a specific window by its bounds.

    Note: On Windows, we capture by screen region since direct window
    capture is more complex. The window_id is used to look up bounds.

    Args:
        window_id: The window handle (HWND).

    Returns:
        PIL Image of the window, or None if capture failed.
    """
    if not WINDOWS_AVAILABLE:
        return None

    # Find the window to get its current bounds
    for win in gw.getAllWindows():
        if win._hWnd == window_id:
            with mss.mss() as sct:
                monitor = {
                    "left": win.left,
                    "top": win.top,
                    "width": win.width,
                    "height": win.height,
                }
                screenshot = sct.grab(monitor)
                return Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")

    return None
