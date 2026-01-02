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
from Xlib.ext import randr

from .. import log

logger = log.get_logger()


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
    """Get window geometry in absolute screen coordinates."""
    try:
        disp = _get_display()
        geom = window.get_geometry()
        # Translate to root window coordinates for absolute screen position
        root = disp.screen().root
        coords = root.translate_coords(window, 0, 0)
        return {
            "x": coords.x,
            "y": coords.y,
            "width": geom.width,
            "height": geom.height,
        }
    except (BadWindow, BadDrawable):
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
    """Get the current bounds of a window by its ID in absolute screen coordinates.

    Args:
        window_id: The X11 window ID (XID).

    Returns:
        Bounds dictionary with x, y, width, height in root coordinates, or None if not found.
    """
    disp = _get_display()
    try:
        window = disp.create_resource_object("window", window_id)
        geom = window.get_geometry()

        # Translate to root window coordinates for absolute screen position
        # This is critical for multi-monitor setups
        root = disp.screen().root
        coords = root.translate_coords(window, 0, 0)

        return {
            "x": coords.x,
            "y": coords.y,
            "width": geom.width,
            "height": geom.height,
        }
    except (BadWindow, BadDrawable):
        return None


def _get_title_bar_height(window_id: int) -> int:
    """Detect the title bar height for CSD (client-side decoration) windows.

    Only returns a non-zero value for GTK/CSD windows where the title bar
    is part of the client window content. For SSD (server-side decoration)
    windows, the WM draws the title bar separately and X11 capture doesn't
    include it, so we return 0.

    Args:
        window_id: The X11 window ID (XID).

    Returns:
        Title bar height in pixels for CSD windows, 0 for SSD windows.
    """
    disp = _get_display()
    try:
        window = disp.create_resource_object("window", window_id)

        # Only use _GTK_FRAME_EXTENTS for CSD detection
        # This property is only set by GTK apps that draw their own title bar
        # For SSD apps (like RetroArch), the WM draws the title bar separately
        # and X11 get_image() doesn't include it
        gtk_frame_extents = disp.intern_atom('_GTK_FRAME_EXTENTS')
        prop = window.get_full_property(gtk_frame_extents, Xatom.CARDINAL)
        if prop and len(prop.value) >= 4:
            # Format: left, right, top, bottom
            top = prop.value[2]
            logger.debug("gtk frame extents (CSD)", left=prop.value[0], right=prop.value[1],
                        top=prop.value[2], bottom=prop.value[3])
            if top > 0:
                return top

        # No _GTK_FRAME_EXTENTS means SSD - WM draws title bar separately
        # X11 capture doesn't include it, so no cropping needed

    except (BadWindow, BadDrawable):
        pass

    return 0


def get_content_offset(window_id: int) -> tuple[int, int]:
    """Get the offset of the content area within a window.

    This finds the content child window (if any) and returns its position
    relative to the parent window. Used by overlay to align with captured content.

    When no content child window is found, returns the title bar height offset
    (since capture will crop the title bar in that case).

    Args:
        window_id: The X11 window ID (XID).

    Returns:
        Tuple of (x_offset, y_offset) in pixels.
    """
    disp = _get_display()
    try:
        window = disp.create_resource_object("window", window_id)
        content_info = _find_content_window(window)
        if content_info:
            return (content_info[1], content_info[2])

        # No content child found - capture will crop title bar
        # unless window is fullscreen
        if not _is_fullscreen(window_id):
            title_bar = _get_title_bar_height(window_id)
            return (0, title_bar)
    except (BadWindow, BadDrawable):
        pass
    return (0, 0)


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


# Cache for monitor list (RANDR queries can cause deadlocks, cache for entire session)
_monitors_cache: list[dict] = []


def _get_monitors() -> list[dict]:
    """Get list of monitors, cached for the entire session."""
    global _monitors_cache

    if _monitors_cache:
        return _monitors_cache

    disp = _get_display()
    monitors = []

    try:
        root = disp.screen().root
        resources = randr.get_screen_resources(root)

        for output in resources.outputs:
            output_info = randr.get_output_info(root, output, resources.config_timestamp)
            if output_info.crtc:
                crtc_info = randr.get_crtc_info(root, output_info.crtc, resources.config_timestamp)
                monitor = {
                    "x": crtc_info.x,
                    "y": crtc_info.y,
                    "width": crtc_info.width,
                    "height": crtc_info.height,
                }
                monitors.append(monitor)
    except Exception:
        pass

    if monitors:
        _monitors_cache = monitors

    return _monitors_cache


def get_display_bounds_for_window(window_id: int, debug: bool = False) -> Optional[dict]:
    """Get the display bounds for the monitor containing the window.

    For multi-monitor setups, finds which monitor contains the window
    and returns that monitor's bounds.

    Args:
        window_id: The X11 window ID to find the containing monitor for.
        debug: If True, print debug information.

    Returns:
        Dictionary with x, y, width, height of the monitor, or None if not found.
    """
    # Get window position to find which monitor it's on
    window_bounds = _get_window_bounds(window_id)
    if window_bounds and debug:
        logger.debug("window bounds for display lookup", **window_bounds)

    # Get monitors (cached to avoid RANDR deadlocks)
    monitors = _get_monitors()

    if not monitors:
        if debug:
            logger.debug("no monitors found via RANDR")
        return None

    if debug:
        for monitor in monitors:
            logger.debug("found monitor", **monitor)

    # If we have window bounds, find the monitor containing the window center
    if window_bounds:
        win_center_x = window_bounds["x"] + window_bounds["width"] // 2
        win_center_y = window_bounds["y"] + window_bounds["height"] // 2

        for monitor in monitors:
            mon_x = monitor["x"]
            mon_y = monitor["y"]
            mon_right = mon_x + monitor["width"]
            mon_bottom = mon_y + monitor["height"]

            if mon_x <= win_center_x < mon_right and mon_y <= win_center_y < mon_bottom:
                if debug:
                    logger.debug("window on monitor", win_center=(win_center_x, win_center_y), monitor=monitor)
                return monitor

        # Window center not on any monitor, use first
        if debug:
            logger.debug("window center not on any monitor, using first", win_center=(win_center_x, win_center_y))

    # Fallback: return first monitor
    if debug:
        logger.debug("using first monitor as fallback")
    return monitors[0]


def _find_content_window(window) -> Optional[tuple]:
    """Find the largest child window (likely the content area).

    For CSD (client-side decoration) windows, the actual content is often
    in a child window, while the parent includes title bar and shadows.

    Args:
        window: The X11 window object.

    Returns:
        Tuple of (child_window, x_offset, y_offset) or None if no suitable child.
    """
    try:
        children = window.query_tree().children
        if not children:
            return None

        # Find the largest child window (by area)
        best_child = None
        best_area = 0
        best_offset = (0, 0)

        for child in children:
            try:
                geom = child.get_geometry()
                area = geom.width * geom.height
                # Must be reasonably sized (> 100x100) and larger than current best
                if geom.width > 100 and geom.height > 100 and area > best_area:
                    best_child = child
                    best_area = area
                    best_offset = (geom.x, geom.y)
            except (BadWindow, BadDrawable):
                continue

        return (best_child, best_offset[0], best_offset[1]) if best_child else None

    except (BadWindow, BadDrawable):
        return None


def capture_window(window_id: int, title_bar_height: int = None) -> Optional[Image.Image]:
    """Capture a screenshot of a specific window.

    For CSD windows (with client-side decorations), this will attempt to
    capture the content child window directly, avoiding title bars and shadows.

    Args:
        window_id: The X11 window ID (XID) of the window to capture.
        title_bar_height: Height of window title bar to crop. If None, auto-detects.
                         Only used as fallback if no content window found.

    Returns:
        PIL Image of the window content, or None if capture failed.
    """
    if title_bar_height is None:
        title_bar_height = _get_title_bar_height(window_id)
    disp = _get_display()

    try:
        window = disp.create_resource_object("window", window_id)

        # Check if window is viewable (ready for capture)
        attrs = window.get_attributes()
        if attrs.map_state != X.IsViewable:
            return None

        # Try to find content child window (for CSD windows)
        content_info = _find_content_window(window)
        if content_info:
            target_window = content_info[0]
            # Content window found - capture it directly (no cropping needed)
            crop_title_bar = False
        else:
            target_window = window
            crop_title_bar = True

        # Get window geometry
        geom = target_window.get_geometry()
        width = geom.width
        height = geom.height
        depth = geom.depth

        if width <= 0 or height <= 0:
            return None

        # Capture the window contents
        # ZPixmap format gives us packed pixel data
        raw = target_window.get_image(
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

        # Only crop title bar if we couldn't find a content window
        if crop_title_bar:
            is_fullscreen = _is_fullscreen(window_id)
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
        # Dedicated display connection for capture thread (thread-safety)
        self._capture_display: Optional[display.Display] = None
        # Flag set when window becomes invalid (e.g., fullscreen transition)
        self._window_invalid = False

    def start(self):
        """Start the capture stream in background."""
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def _capture_window(self) -> Optional[Image.Image]:
        """Capture window using the thread's dedicated display connection.

        This is similar to the module-level capture_window() but uses
        self._capture_display for thread-safety.

        Returns:
            PIL Image of the window content, or None if capture failed.
        """
        if self._capture_display is None:
            return None

        disp = self._capture_display

        try:
            window = disp.create_resource_object("window", self._window_id)

            # Check if window is viewable (ready for capture)
            # During fullscreen transitions, window may exist but not be ready
            attrs = window.get_attributes()
            if attrs.map_state != X.IsViewable:
                return None

            # Try to find content child window (for CSD windows)
            content_info = _find_content_window(window)
            if content_info:
                target_window = content_info[0]
                crop_title_bar = False
            else:
                target_window = window
                crop_title_bar = True

            # Get window geometry
            geom = target_window.get_geometry()
            width = geom.width
            height = geom.height
            depth = geom.depth

            if width <= 0 or height <= 0:
                return None

            # Capture the window contents
            raw = target_window.get_image(
                0, 0,
                width, height,
                X.ZPixmap,
                0xFFFFFFFF
            )

            data = raw.data

            if depth == 24 or depth == 32:
                expected_size = width * height * 4
                if len(data) < expected_size:
                    logger.debug("capture failed: insufficient data", expected=expected_size, actual=len(data))
                    return None

                image = Image.frombytes(
                    "RGBA", (width, height),
                    bytes(data[:expected_size]),
                    "raw", "BGRA"
                )
                image = image.convert("RGB")

            elif depth == 16:
                expected_size = width * height * 2
                if len(data) < expected_size:
                    logger.debug("capture failed: insufficient data (16-bit)", expected=expected_size, actual=len(data))
                    return None

                pixels = []
                for i in range(0, expected_size, 2):
                    pixel = struct.unpack("<H", data[i:i+2])[0]
                    r = ((pixel >> 11) & 0x1F) << 3
                    g = ((pixel >> 5) & 0x3F) << 2
                    b = (pixel & 0x1F) << 3
                    pixels.extend([r, g, b])

                image = Image.frombytes("RGB", (width, height), bytes(pixels))

            else:
                logger.debug("capture failed: unsupported depth", depth=depth)
                return None

            # Only crop title bar if we couldn't find a content window
            if crop_title_bar:
                is_fullscreen = _is_fullscreen(self._window_id)
                if not is_fullscreen:
                    title_bar = _get_title_bar_height(self._window_id)
                    if height > title_bar:
                        image = image.crop((0, title_bar, width, height))

            return image

        except BadDrawable:
            # Window was destroyed (e.g., fullscreen transition)
            logger.debug("capture BadDrawable", window_id=self._window_id)
            self._window_invalid = True
            with self._frame_lock:
                self._latest_frame = None
            return None
        except BadWindow:
            # Window was destroyed
            logger.debug("capture BadWindow", window_id=self._window_id)
            self._window_invalid = True
            with self._frame_lock:
                self._latest_frame = None
            return None
        except Exception as e:
            logger.debug("capture failed: exception", error=str(e))
            return None

    @property
    def window_invalid(self) -> bool:
        """Check if the window ID is invalid (window was destroyed)."""
        return self._window_invalid

    def _capture_loop(self):
        """Background thread that continuously captures frames."""
        # Create dedicated display connection for this thread (thread-safety)
        # X11 Display objects are not thread-safe, so each thread needs its own
        self._capture_display = display.Display()
        logger.debug("capture thread started", window_id=self._window_id)
        first_frame = True

        while self._running and not self._window_invalid:
            start = time.time()
            frame = self._capture_window()
            elapsed = time.time() - start
            if frame:
                with self._frame_lock:
                    self._latest_frame = frame
                if first_frame:
                    logger.debug("first frame captured", window_id=self._window_id, elapsed_ms=int(elapsed*1000))
                    first_frame = False
            elif elapsed > 0.1:  # Log slow failures
                logger.debug("capture slow/failed", window_id=self._window_id, elapsed_ms=int(elapsed*1000))
            time.sleep(0.033)  # ~30 FPS

        logger.debug("capture thread exiting", window_id=self._window_id, invalid=self._window_invalid)

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
        # Close the dedicated display connection
        if self._capture_display:
            try:
                self._capture_display.close()
            except Exception:
                pass
            self._capture_display = None
