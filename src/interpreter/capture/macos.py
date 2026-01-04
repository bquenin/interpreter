"""macOS-specific window capture using PyObjC/Quartz."""

import os
import platform
import threading
import time

import numpy as np
from AppKit import NSClosableWindowMask, NSMiniaturizableWindowMask, NSScreen, NSTitledWindowMask, NSWindow
from numpy.typing import NDArray
from Quartz import CoreGraphics as CG

from .. import log

logger = log.get_logger()

# Fixed capture interval (4 FPS)
CAPTURE_INTERVAL = 0.25


def _get_macos_version() -> str:
    """Get macOS version string."""
    return f"macOS {platform.mac_ver()[0]}"


def _get_title_bar_height_pixels() -> int:
    """Get the standard macOS title bar height in pixels.

    Uses NSWindow API to get the title bar height in points,
    then multiplies by the display scale factor.

    Returns:
        Title bar height in pixels for the current display.
    """
    # Get scale factor from main screen
    scale = NSScreen.mainScreen().backingScaleFactor()

    # Calculate title bar height using NSWindow API
    content_rect = ((0, 0), (100, 100))
    style_mask = NSTitledWindowMask | NSClosableWindowMask | NSMiniaturizableWindowMask
    frame_rect = NSWindow.frameRectForContentRect_styleMask_(content_rect, style_mask)

    # Difference in height is the title bar (in points)
    title_bar_points = frame_rect[1][1] - content_rect[1][1]

    # Convert to pixels
    return int(title_bar_points * scale)


def get_window_list() -> list[dict]:
    """Get list of all windows with their properties.

    Returns:
        List of window dictionaries with keys: id, title, bounds
    """
    windows = []
    own_pid = os.getpid()

    # Use kCGWindowListOptionAll to include windows on other Spaces (e.g., fullscreen apps)
    window_list = CG.CGWindowListCopyWindowInfo(
        CG.kCGWindowListOptionAll | CG.kCGWindowListExcludeDesktopElements, CG.kCGNullWindowID
    )

    for window in window_list:
        window_id = window.get(CG.kCGWindowNumber)
        title = window.get(CG.kCGWindowName, "")
        owner = window.get(CG.kCGWindowOwnerName, "")
        owner_pid = window.get(CG.kCGWindowOwnerPID, 0)
        bounds = window.get(CG.kCGWindowBounds, {})

        # Only include normal application windows (layer 0) with a title
        # Exclude our own windows (by PID or by title)
        layer = window.get(CG.kCGWindowLayer, -1)
        if layer != 0 or not title or owner_pid == own_pid or title == "Interpreter":
            continue

        windows.append(
            {
                "id": window_id,
                "title": title,
                "owner": owner,
                "bounds": {
                    "x": int(bounds.get("X", 0)),
                    "y": int(bounds.get("Y", 0)),
                    "width": int(bounds.get("Width", 0)),
                    "height": int(bounds.get("Height", 0)),
                },
            }
        )

    # Sort alphabetically by title
    return sorted(windows, key=lambda w: w["title"].lower())


def find_window_by_title(title_substring: str) -> dict | None:
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


def _get_window_bounds(window_id: int) -> dict | None:
    """Get the current bounds of a window by its ID.

    Args:
        window_id: The CGWindowID of the window.

    Returns:
        Bounds dictionary with x, y, width, height, or None if not found.
    """
    window_list = CG.CGWindowListCopyWindowInfo(CG.kCGWindowListOptionIncludingWindow, window_id)

    for window in window_list:
        if window.get(CG.kCGWindowNumber) == window_id:
            bounds = window.get(CG.kCGWindowBounds, {})
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
    (err, display_ids, display_count) = CG.CGGetActiveDisplayList(max_displays, None, None)
    if err != 0 or display_count == 0:
        return False

    # Find which display contains this window
    window_center_x = bounds["x"] + bounds["width"] // 2
    window_center_y = bounds["y"] + bounds["height"] // 2

    for display_id in display_ids[:display_count]:
        display_bounds = CG.CGDisplayBounds(display_id)
        dx = int(display_bounds.origin.x)
        dy = int(display_bounds.origin.y)
        dw = int(display_bounds.size.width)
        dh = int(display_bounds.size.height)

        # Check if window center is on this display
        if dx <= window_center_x < dx + dw and dy <= window_center_y < dy + dh:
            # Check if window fills this display (with tolerance for menu bar ~50px)
            is_fullscreen = (
                bounds["x"] == dx and bounds["y"] <= dy + 50 and bounds["width"] == dw and bounds["height"] >= dh - 50
            )
            return is_fullscreen

    return False


def get_content_offset(window_id: int) -> tuple[int, int]:
    """Get the offset of the content area within a window.

    On macOS, capture crops the title bar, so we report that offset.
    In fullscreen mode, no cropping happens.

    Args:
        window_id: The CGWindowID of the window.

    Returns:
        Tuple of (x_offset, y_offset) in pixels.
    """
    if _is_fullscreen(window_id):
        return (0, 0)
    return (0, _get_title_bar_height_pixels())


def capture_window(window_id: int) -> NDArray[np.uint8] | None:
    """Capture a screenshot of a specific window using CGWindowListCreateImage.

    This captures the actual window content, not the screen region,
    so overlapping windows (like the subtitle overlay) won't be included.
    Automatically detects fullscreen mode and skips title bar cropping.
    Uses macOS API to determine correct title bar height for current display.

    Args:
        window_id: The CGWindowID of the window to capture.

    Returns:
        Numpy array (H, W, 4) in BGRA format, or None if capture failed.
    """
    # Check if fullscreen before capturing
    is_fullscreen = _is_fullscreen(window_id)

    # Get title bar height from macOS API (accounts for display scale)
    title_bar_height = _get_title_bar_height_pixels() if not is_fullscreen else 0

    # Capture the specific window only (not the screen region)
    # kCGWindowListOptionIncludingWindow captures only this window
    # kCGWindowImageBoundsIgnoreFraming excludes window shadow
    cg_image = CG.CGWindowListCreateImage(
        CG.CGRectNull,  # Capture the window's own bounds
        CG.kCGWindowListOptionIncludingWindow,
        window_id,
        CG.kCGWindowImageBoundsIgnoreFraming,
    )

    if cg_image is None:
        return None

    # Get image dimensions
    width = CG.CGImageGetWidth(cg_image)
    height = CG.CGImageGetHeight(cg_image)
    bytes_per_row = CG.CGImageGetBytesPerRow(cg_image)

    if width == 0 or height == 0:
        return None

    # Get the raw pixel data
    data_provider = CG.CGImageGetDataProvider(cg_image)
    data = CG.CGDataProviderCopyData(data_provider)

    # Convert to numpy array in BGRA format
    # Need to account for bytes_per_row which may include padding
    if bytes_per_row == width * 4:
        # No padding, reshape directly
        arr = np.frombuffer(data, dtype=np.uint8).reshape((height, width, 4)).copy()
    else:
        # Has padding, need to handle stride manually
        arr = np.frombuffer(data, dtype=np.uint8).reshape((height, bytes_per_row))
        # Take only the actual pixel data (width * 4 bytes per row)
        arr = arr[:, : width * 4].reshape((height, width, 4)).copy()

    # Crop out the title bar if needed
    if title_bar_height > 0 and height > title_bar_height:
        arr = arr[title_bar_height:, :, :]

    return arr


def _get_window_info(window_id: int) -> dict | None:
    """Get window info including owner name.

    Args:
        window_id: The CGWindowID of the window.

    Returns:
        Dictionary with title, owner, bounds or None if not found.
    """
    window_list = CG.CGWindowListCopyWindowInfo(CG.kCGWindowListOptionIncludingWindow, window_id)

    for window in window_list:
        if window.get(CG.kCGWindowNumber) == window_id:
            return {
                "title": window.get(CG.kCGWindowName, ""),
                "owner": window.get(CG.kCGWindowOwnerName, ""),
            }
    return None


class MacOSCaptureStream:
    """Continuous window capture wrapping existing Quartz capture.

    Provides the same streaming interface as WindowsCaptureStream for
    platform-agnostic capture code. Captures at fixed 4 FPS.
    """

    def __init__(self, window_id: int):
        """Initialize the capture stream.

        Args:
            window_id: The CGWindowID of the window to capture.
        """
        self._window_id = window_id
        self._latest_frame: NDArray[np.uint8] | None = None
        self._frame_lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._first_frame_logged = False

    def start(self):
        """Start the capture stream in background."""
        # Log capture configuration (window title already logged by WindowCapture)
        window_info = _get_window_info(self._window_id)
        owner = window_info.get("owner", "") if window_info else ""
        log_kwargs = {"macos_version": _get_macos_version()}
        if owner:
            log_kwargs["owner"] = owner
        logger.info("capture config", **log_kwargs)

        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def _capture_loop(self):
        """Background thread that captures frames at fixed 4 FPS."""
        while self._running:
            frame = capture_window(self._window_id)
            if frame is not None:
                # Log first frame info
                if not self._first_frame_logged:
                    self._first_frame_logged = True
                    height, width = frame.shape[:2]
                    is_fullscreen = _is_fullscreen(self._window_id)
                    logger.info(
                        "capture started",
                        resolution=f"{width}x{height}",
                        fullscreen=is_fullscreen,
                    )

                with self._frame_lock:
                    self._latest_frame = frame
            time.sleep(CAPTURE_INTERVAL)

    def get_frame(self) -> NDArray[np.uint8] | None:
        """Get the latest captured frame.

        Returns:
            Numpy array (H, W, 4) in BGRA format, or None if no frame available.
        """
        with self._frame_lock:
            return self._latest_frame

    def stop(self):
        """Stop the capture stream."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
