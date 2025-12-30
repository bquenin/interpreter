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


def _is_fullscreen(window_id: int) -> bool:
    """Check if a window is in fullscreen mode.

    Detects fullscreen by comparing window bounds to display bounds.
    Handles multi-monitor setups by finding the display containing the window.

    Args:
        window_id: The CGWindowID of the window.

    Returns:
        True if window appears to be fullscreen, False otherwise.
    """
    bounds = _get_window_bounds(window_id)
    if bounds is None:
        return False

    # Get all active displays
    max_displays = 16
    (err, display_ids, display_count) = Quartz.CGGetActiveDisplayList(max_displays, None, None)
    if err != 0 or display_count == 0:
        return False

    # Find which display contains this window
    window_center_x = bounds["x"] + bounds["width"] // 2
    window_center_y = bounds["y"] + bounds["height"] // 2

    for display_id in display_ids[:display_count]:
        display_bounds = Quartz.CGDisplayBounds(display_id)
        dx = int(display_bounds.origin.x)
        dy = int(display_bounds.origin.y)
        dw = int(display_bounds.size.width)
        dh = int(display_bounds.size.height)

        # Check if window center is on this display
        if dx <= window_center_x < dx + dw and dy <= window_center_y < dy + dh:
            # Check if window fills this display (with tolerance for menu bar ~50px)
            is_fullscreen = (
                bounds["x"] == dx and
                bounds["y"] <= dy + 50 and
                bounds["width"] == dw and
                bounds["height"] >= dh - 50
            )
            return is_fullscreen

    return False


def get_display_bounds_for_window(window_id: int) -> Optional[dict]:
    """Get the display bounds for the display containing a window.

    Args:
        window_id: The CGWindowID of the window.

    Returns:
        Display bounds dict with x, y, width, height, or None if not found.
    """
    bounds = _get_window_bounds(window_id)
    if bounds is None:
        return None

    # Get all active displays
    max_displays = 16
    (err, display_ids, display_count) = Quartz.CGGetActiveDisplayList(max_displays, None, None)
    if err != 0 or display_count == 0:
        return None

    # Find which display contains this window's center
    window_center_x = bounds["x"] + bounds["width"] // 2
    window_center_y = bounds["y"] + bounds["height"] // 2

    for display_id in display_ids[:display_count]:
        display_bounds = Quartz.CGDisplayBounds(display_id)
        dx = int(display_bounds.origin.x)
        dy = int(display_bounds.origin.y)
        dw = int(display_bounds.size.width)
        dh = int(display_bounds.size.height)

        if dx <= window_center_x < dx + dw and dy <= window_center_y < dy + dh:
            return {
                "x": dx,
                "y": dy,
                "width": dw,
                "height": dh,
            }

    return None


def capture_window(window_id: int, title_bar_height: int = 30) -> Optional[Image.Image]:
    """Capture a screenshot of a specific window using CGWindowListCreateImage.

    This captures the actual window content, not the screen region,
    so overlapping windows (like the subtitle overlay) won't be included.
    Automatically detects fullscreen mode and skips title bar cropping.

    Args:
        window_id: The CGWindowID of the window to capture.
        title_bar_height: Height of window title bar to crop (default: 30).
                         Ignored for fullscreen windows.

    Returns:
        PIL Image of the window content (excluding title bar), or None if capture failed.
    """
    # Check if fullscreen before capturing
    is_fullscreen = _is_fullscreen(window_id)

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
    bytes_per_row = Quartz.CGImageGetBytesPerRow(cg_image)

    if width == 0 or height == 0:
        return None

    # Get the raw pixel data
    data_provider = Quartz.CGImageGetDataProvider(cg_image)
    data = Quartz.CGDataProviderCopyData(data_provider)

    # Create PIL Image from raw data (BGRA format)
    # Need to account for bytes_per_row which may include padding
    if bytes_per_row == width * 4:
        # No padding, can use frombytes directly
        image = Image.frombytes("RGBA", (width, height), bytes(data), "raw", "BGRA")
    else:
        # Has padding, need to handle stride manually
        import numpy as np
        arr = np.frombuffer(data, dtype=np.uint8).reshape((height, bytes_per_row))
        # Take only the actual pixel data (width * 4 bytes per row)
        arr = arr[:, :width * 4].reshape((height, width, 4))
        # Convert from BGRA to RGBA
        image = Image.fromarray(arr[:, :, [2, 1, 0, 3]], "RGBA")

    # Convert to RGB (drop alpha channel)
    image = image.convert("RGB")

    # Crop out the title bar if not fullscreen
    if not is_fullscreen and title_bar_height > 0 and height > title_bar_height:
        image = image.crop((0, title_bar_height, width, height))

    return image
