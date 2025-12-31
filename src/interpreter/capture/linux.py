"""Linux-specific window capture using X11 via python-xlib.

This module captures windows through the X11 protocol, which works for:
- Native X11 applications
- XWayland applications (X11 apps running on Wayland)

Most retro game emulators run under XWayland, so this covers the primary use case.
"""

import struct
import threading
import time
from typing import Optional

from PIL import Image
from Xlib import X, display, Xatom
from Xlib.error import BadWindow, BadDrawable


# Module-level display connection (reused for efficiency)
_display: Optional[display.Display] = None


def _get_display() -> display.Display:
    """Get or create a shared X11 display connection."""
    global _display
    if _display is None:
        _display = display.Display()
    return _display


def _get_window_title(disp: display.Display, window) -> str:
    """Get the title of an X11 window."""
    try:
        # Try _NET_WM_NAME first (UTF-8, modern standard)
        net_wm_name = disp.intern_atom("_NET_WM_NAME")
        utf8_string = disp.intern_atom("UTF8_STRING")

        prop = window.get_full_property(net_wm_name, utf8_string)
        if prop and prop.value:
            return prop.value.decode("utf-8", errors="replace")

        # Fall back to WM_NAME (legacy)
        prop = window.get_full_property(Xatom.WM_NAME, Xatom.STRING)
        if prop and prop.value:
            if isinstance(prop.value, bytes):
                return prop.value.decode("latin-1", errors="replace")
            return str(prop.value)
    except (BadWindow, UnicodeDecodeError):
        pass

    return ""


def _get_window_geometry(window) -> Optional[dict]:
    """Get window geometry (position and size)."""
    try:
        geom = window.get_geometry()
        return {
            "x": geom.x,
            "y": geom.y,
            "width": geom.width,
            "height": geom.height,
        }
    except BadWindow:
        return None


def _enumerate_windows(disp: display.Display, parent=None) -> list[dict]:
    """Recursively enumerate all visible windows with titles."""
    if parent is None:
        parent = disp.screen().root

    windows = []

    try:
        children = parent.query_tree().children
    except BadWindow:
        return windows

    for child in children:
        try:
            # Get window attributes
            attrs = child.get_attributes()
            if attrs.map_state != X.IsViewable:
                continue

            title = _get_window_title(disp, child)
            geom = _get_window_geometry(child)

            # Only include windows with a title and reasonable size
            if title and geom and geom["width"] > 1 and geom["height"] > 1:
                windows.append({
                    "id": child.id,
                    "title": title,
                    "bounds": geom,
                })

            # Recurse into children
            windows.extend(_enumerate_windows(disp, child))

        except BadWindow:
            continue

    return windows


def get_window_list() -> list[dict]:
    """Get list of all windows with their properties.

    Returns:
        List of window dictionaries with keys: id, title, bounds
    """
    disp = _get_display()
    windows = _enumerate_windows(disp)
    # Sort by window ID for consistent ordering
    windows.sort(key=lambda w: w["id"])
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


def _get_window_bounds(window_id: int) -> Optional[dict]:
    """Get the current bounds of a window by its ID.

    Args:
        window_id: The X11 window ID (XID).

    Returns:
        Bounds dictionary with x, y, width, height, or None if not found.
    """
    disp = _get_display()
    try:
        window = disp.create_resource_object("window", window_id)
        return _get_window_geometry(window)
    except BadWindow:
        return None


def _is_fullscreen(window_id: int) -> bool:
    """Check if a window is in fullscreen mode.

    Detects fullscreen by comparing window bounds to screen bounds.

    Args:
        window_id: The X11 window ID.

    Returns:
        True if window appears to be fullscreen, False otherwise.
    """
    disp = _get_display()
    bounds = _get_window_bounds(window_id)
    if bounds is None:
        return False

    # Get screen dimensions
    screen = disp.screen()
    screen_width = screen.width_in_pixels
    screen_height = screen.height_in_pixels

    # Check if window fills the screen (with small tolerance)
    tolerance = 50
    is_fullscreen = (
        bounds["x"] <= tolerance and
        bounds["y"] <= tolerance and
        bounds["width"] >= screen_width - tolerance and
        bounds["height"] >= screen_height - tolerance
    )

    return is_fullscreen


def capture_window(window_id: int, title_bar_height: int = 30) -> Optional[Image.Image]:
    """Capture a screenshot of a specific window.

    Args:
        window_id: The X11 window ID (XID) of the window to capture.
        title_bar_height: Height of window title bar to crop (default: 30).
                         Ignored for fullscreen windows.

    Returns:
        PIL Image of the window content, or None if capture failed.
    """
    disp = _get_display()

    try:
        window = disp.create_resource_object("window", window_id)

        # Get window geometry
        geom = window.get_geometry()
        width = geom.width
        height = geom.height
        depth = geom.depth

        if width <= 0 or height <= 0:
            return None

        # Capture the window contents
        # ZPixmap format gives us packed pixel data
        raw = window.get_image(
            0, 0,           # x, y offset
            width, height,  # dimensions
            X.ZPixmap,      # format (packed pixels)
            0xFFFFFFFF      # plane mask (all planes)
        )

        # Get the raw data
        data = raw.data

        if depth == 24 or depth == 32:
            # 32-bit BGRX or BGRA format (X11 typically uses this)
            expected_size = width * height * 4
            if len(data) < expected_size:
                return None

            # Load as BGRA, then convert to RGB
            image = Image.frombytes(
                "RGBA", (width, height),
                bytes(data[:expected_size]),
                "raw", "BGRA"
            )
            image = image.convert("RGB")

        elif depth == 16:
            # 16-bit RGB (5-6-5 format)
            expected_size = width * height * 2
            if len(data) < expected_size:
                return None

            # Convert 5-6-5 to RGB24
            pixels = []
            for i in range(0, expected_size, 2):
                pixel = struct.unpack("<H", data[i:i+2])[0]
                r = ((pixel >> 11) & 0x1F) << 3
                g = ((pixel >> 5) & 0x3F) << 2
                b = (pixel & 0x1F) << 3
                pixels.extend([r, g, b])

            image = Image.frombytes("RGB", (width, height), bytes(pixels))

        else:
            # Unsupported depth
            return None

        # Check if fullscreen
        is_fullscreen = _is_fullscreen(window_id)

        # Crop out the title bar if not fullscreen
        if not is_fullscreen and title_bar_height > 0 and height > title_bar_height:
            image = image.crop((0, title_bar_height, width, height))

        return image

    except BadWindow:
        return None
    except BadDrawable:
        return None
    except Exception:
        return None


class LinuxCaptureStream:
    """Continuous window capture using X11.

    Provides the same streaming interface as MacOSCaptureStream and
    WindowsCaptureStream for platform-agnostic capture code.
    """

    def __init__(self, window_id: int):
        """Initialize the capture stream.

        Args:
            window_id: The X11 window ID (XID) of the window to capture.
        """
        self._window_id = window_id
        self._latest_frame: Optional[Image.Image] = None
        self._frame_lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        """Start the capture stream in background."""
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def _capture_loop(self):
        """Background thread that continuously captures frames."""
        while self._running:
            frame = capture_window(self._window_id)
            if frame:
                with self._frame_lock:
                    self._latest_frame = frame
            time.sleep(0.033)  # ~30 FPS

    def get_frame(self) -> Optional[Image.Image]:
        """Get the latest captured frame.

        Returns:
            PIL Image of the captured frame, or None if no frame available.
        """
        with self._frame_lock:
            return self._latest_frame

    def stop(self):
        """Stop the capture stream."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
