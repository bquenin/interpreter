"""macOS-specific window capture using PyObjC/Quartz and mss."""

from typing import Optional

from PIL import Image
import mss
import Quartz


def get_window_list() -> list[dict]:
    """Get list of all windows with their properties.

    Returns:
        List of window dictionaries with keys: id, title, bounds
    """
    windows = []
    window_list = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID
    )

    for window in window_list:
        window_id = window.get(Quartz.kCGWindowNumber)
        title = window.get(Quartz.kCGWindowName, "")
        owner = window.get(Quartz.kCGWindowOwnerName, "")
        bounds = window.get(Quartz.kCGWindowBounds, {})

        if title or owner:  # Skip windows without any identifiable name
            windows.append({
                "id": window_id,
                "title": title or owner,
                "owner": owner,
                "bounds": {
                    "x": int(bounds.get("X", 0)),
                    "y": int(bounds.get("Y", 0)),
                    "width": int(bounds.get("Width", 0)),
                    "height": int(bounds.get("Height", 0)),
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
        if title_lower in window["owner"].lower():
            return window

    return None


def _get_window_bounds(window_id: int) -> Optional[dict]:
    """Get the current bounds of a window by its ID.

    Args:
        window_id: The CGWindowID of the window.

    Returns:
        Bounds dictionary with x, y, width, height, or None if not found.
    """
    window_list = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionIncludingWindow,
        window_id
    )

    for window in window_list:
        if window.get(Quartz.kCGWindowNumber) == window_id:
            bounds = window.get(Quartz.kCGWindowBounds, {})
            return {
                "x": int(bounds.get("X", 0)),
                "y": int(bounds.get("Y", 0)),
                "width": int(bounds.get("Width", 0)),
                "height": int(bounds.get("Height", 0)),
            }

    return None


def capture_window(window_id: int) -> Optional[Image.Image]:
    """Capture a screenshot of a specific window using mss.

    Args:
        window_id: The CGWindowID of the window to capture.

    Returns:
        PIL Image of the window, or None if capture failed.
    """
    # Get current window bounds
    bounds = _get_window_bounds(window_id)
    if bounds is None:
        return None

    if bounds["width"] == 0 or bounds["height"] == 0:
        return None

    # Use mss to capture the screen region
    with mss.mss() as sct:
        monitor = {
            "left": bounds["x"],
            "top": bounds["y"],
            "width": bounds["width"],
            "height": bounds["height"],
        }

        try:
            screenshot = sct.grab(monitor)
            # Convert to PIL Image (mss returns BGRA, we want RGB)
            image = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
            return image
        except Exception:
            return None
