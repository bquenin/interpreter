"""macOS-specific window capture using PyObjC/Quartz."""

from typing import Optional

from PIL import Image
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


def capture_window(window_id: int, title_bar_height: int = 30) -> Optional[Image.Image]:
    """Capture a screenshot of a specific window using CGWindowListCreateImage.

    This captures the actual window content, not the screen region,
    so overlapping windows (like the subtitle overlay) won't be included.

    Args:
        window_id: The CGWindowID of the window to capture.
        title_bar_height: Height of window title bar to crop (default: 30).
                         Set to 0 to include title bar.

    Returns:
        PIL Image of the window content (excluding title bar), or None if capture failed.
    """
    # Capture the specific window only (not the screen region)
    # kCGWindowListOptionIncludingWindow captures only this window
    # kCGWindowImageBoundsIgnoreFraming excludes window shadow
    cg_image = Quartz.CGWindowListCreateImage(
        Quartz.CGRectNull,  # Capture the window's own bounds
        Quartz.kCGWindowListOptionIncludingWindow,
        window_id,
        Quartz.kCGWindowImageBoundsIgnoreFraming
    )

    if cg_image is None:
        return None

    # Get image dimensions
    width = Quartz.CGImageGetWidth(cg_image)
    height = Quartz.CGImageGetHeight(cg_image)

    if width == 0 or height == 0:
        return None

    # Get the raw pixel data
    data_provider = Quartz.CGImageGetDataProvider(cg_image)
    data = Quartz.CGDataProviderCopyData(data_provider)

    # Create PIL Image from raw data (BGRA format)
    image = Image.frombytes("RGBA", (width, height), bytes(data), "raw", "BGRA")

    # Convert to RGB (drop alpha channel)
    image = image.convert("RGB")

    # Crop out the title bar if requested
    if title_bar_height > 0 and height > title_bar_height:
        image = image.crop((0, title_bar_height, width, height))

    return image
