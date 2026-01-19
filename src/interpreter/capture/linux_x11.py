"""Linux-specific window capture using X11 via python-xlib.

This module captures windows through the X11 protocol, which works for:
- Native X11 applications
- XWayland applications (X11 apps running on Wayland)

Most retro game emulators run under XWayland, so this covers the primary use case.
"""

import os
import threading
import time

import numpy as np
from numpy.typing import NDArray
from Xlib import X, Xatom, display
from Xlib.error import BadDrawable, BadWindow
from Xlib.ext import randr

from .. import log

logger = log.get_logger()


def _get_display_server_info() -> str:
    """Get display server info (X11/Wayland/XWayland)."""
    display = os.environ.get("DISPLAY", "")
    wayland = os.environ.get("WAYLAND_DISPLAY", "")
    if wayland:
        return f"XWayland ({wayland})" if display else f"Wayland ({wayland})"
    return f"X11 ({display})" if display else "unknown"


# Module-level display connection (reused for efficiency)
_display: display.Display | None = None


def _get_display() -> display.Display:
    """Get or create a shared X11 display connection."""
    global _display
    if _display is None:
        try:
            _display = display.Display()
        except Exception as e:
            raise RuntimeError(
                "Cannot connect to X11 display. This application requires X11 or XWayland. "
                "If you're using Wayland, ensure XWayland is installed and running."
            ) from e
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


def _get_window_geometry(window) -> dict | None:
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


def _is_normal_window(disp: display.Display, window) -> bool:
    """Check if a window is a normal application window.

    Uses _NET_WM_WINDOW_TYPE to filter out dialogs, tooltips, etc.
    Windows without this property are assumed to be normal windows.
    """
    try:
        window_type_atom = disp.intern_atom("_NET_WM_WINDOW_TYPE")
        normal_atom = disp.intern_atom("_NET_WM_WINDOW_TYPE_NORMAL")

        prop = window.get_full_property(window_type_atom, Xatom.ATOM)
        if prop and prop.value:
            # Window has explicit type - check if it's NORMAL
            return normal_atom in prop.value

        # No window type property - assume it's a normal window
        return True
    except (BadWindow, BadDrawable):
        return False


def _enumerate_windows(disp: display.Display) -> list[dict]:
    """Enumerate top-level application windows.

    Uses _NET_CLIENT_LIST (EWMH standard) to get managed windows,
    which works correctly with reparenting window managers like KDE/KWin.
    Falls back to root.query_tree() for minimal window managers.
    """
    root = disp.screen().root
    windows = []

    # Try _NET_CLIENT_LIST first (works with reparenting WMs like KDE)
    try:
        net_client_list = disp.intern_atom("_NET_CLIENT_LIST")
        prop = root.get_full_property(net_client_list, Xatom.WINDOW)
        if prop is not None and prop.value is not None:
            window_ids = prop.value
        else:
            # Fallback: direct children of root (for minimal WMs without EWMH)
            window_ids = [child.id for child in root.query_tree().children]
    except BadWindow:
        return windows

    for wid in window_ids:
        try:
            child = disp.create_resource_object("window", wid)

            # Get window attributes
            attrs = child.get_attributes()
            if attrs.map_state != X.IsViewable:
                continue

            # Only include normal application windows
            if not _is_normal_window(disp, child):
                continue

            title = _get_window_title(disp, child)
            geom = _get_window_geometry(child)

            # Only include windows with a title and reasonable size
            if title and geom and geom["width"] > 1 and geom["height"] > 1:
                windows.append(
                    {
                        "id": child.id,
                        "title": title,
                        "bounds": geom,
                    }
                )

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

    return None


def _get_window_bounds(window_id: int) -> dict | None:
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
        gtk_frame_extents = disp.intern_atom("_GTK_FRAME_EXTENTS")
        prop = window.get_full_property(gtk_frame_extents, Xatom.CARDINAL)
        if prop and len(prop.value) >= 4:
            # Format: left, right, top, bottom
            top = prop.value[2]
            logger.debug(
                "gtk frame extents (CSD)",
                left=prop.value[0],
                right=prop.value[1],
                top=prop.value[2],
                bottom=prop.value[3],
            )
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
        bounds["x"] <= tolerance
        and bounds["y"] <= tolerance
        and bounds["width"] >= screen_width - tolerance
        and bounds["height"] >= screen_height - tolerance
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


def _raw_to_numpy(data: bytes, width: int, height: int, depth: int) -> NDArray[np.uint8] | None:
    """Convert raw X11 pixel data to numpy array in BGRA format.

    Handles both 24/32-bit BGRA and 16-bit RGB565 formats.

    Args:
        data: Raw pixel data from X11 get_image().
        width: Image width in pixels.
        height: Image height in pixels.
        depth: Color depth (16, 24, or 32).

    Returns:
        Numpy array (H, W, 4) in BGRA format, or None if conversion failed.
    """
    if depth == 24 or depth == 32:
        expected_size = width * height * 4
        if len(data) < expected_size:
            return None
        # Data is already in BGRA format, just reshape
        arr = np.frombuffer(data[:expected_size], dtype=np.uint8).reshape((height, width, 4)).copy()
        return arr

    elif depth == 16:
        expected_size = width * height * 2
        if len(data) < expected_size:
            return None
        # Convert RGB565 to BGRA
        pixels = np.frombuffer(data[:expected_size], dtype=np.uint16).reshape((height, width))
        r = ((pixels >> 11) & 0x1F).astype(np.uint8) << 3
        g = ((pixels >> 5) & 0x3F).astype(np.uint8) << 2
        b = (pixels & 0x1F).astype(np.uint8) << 3
        a = np.full((height, width), 255, dtype=np.uint8)
        # Stack as BGRA
        arr = np.stack([b, g, r, a], axis=-1)
        return arr

    return None


def _find_content_window(window) -> tuple | None:
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


def _crop_title_bar_if_needed(frame: NDArray[np.uint8], window_id: int, crop_title_bar: bool) -> NDArray[np.uint8]:
    """Crop title bar from frame if needed.

    Uses lazy evaluation - only fetches title bar height if actually needed.

    Args:
        frame: The captured numpy array (H, W, 4) in BGRA format.
        window_id: The X11 window ID.
        crop_title_bar: Whether cropping should be considered.

    Returns:
        Cropped frame if title bar was removed, original frame otherwise.
    """
    if not crop_title_bar or _is_fullscreen(window_id):
        return frame

    title_bar = _get_title_bar_height(window_id)
    if title_bar > 0 and frame.shape[0] > title_bar:
        return frame[title_bar:, :, :]

    return frame


def capture_window(window_id: int) -> NDArray[np.uint8] | None:
    """Capture a screenshot of a specific window.

    For CSD windows (with client-side decorations), this will attempt to
    capture the content child window directly, avoiding title bars and shadows.

    Args:
        window_id: The X11 window ID (XID) of the window to capture.

    Returns:
        Numpy array (H, W, 4) in BGRA format, or None if capture failed.
    """
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
            0,
            0,  # x, y offset
            width,
            height,  # dimensions
            X.ZPixmap,  # format (packed pixels)
            0xFFFFFFFF,  # plane mask (all planes)
        )

        # Convert raw pixel data to numpy BGRA array
        frame = _raw_to_numpy(raw.data, width, height, depth)
        if frame is None:
            return None

        return _crop_title_bar_if_needed(frame, window_id, crop_title_bar)

    except BadWindow:
        return None
    except BadDrawable:
        return None
    except Exception:
        return None


class LinuxCaptureStream:
    """Continuous background window capture using X11.

    Captures frames in a background thread at a fixed 4 FPS interval.
    The main thread can get the latest frame without blocking.

    Provides the same interface as MacOSCaptureStream and WindowsCaptureStream
    for platform-agnostic capture code.
    """

    # Thresholds for capture time warnings
    CAPTURE_TIME_WARNING_MS = 100  # Warn if capture takes longer than this
    CAPTURE_TIME_SAMPLE_COUNT = 5  # Number of frames to sample for average

    def __init__(self, window_id: int, capture_interval: float = 0.25):
        """Initialize the capture stream.

        Args:
            window_id: The X11 window ID (XID) of the window to capture.
            capture_interval: Minimum seconds between captures.
        """
        self._window_id = window_id
        self._capture_interval = capture_interval
        self._latest_frame: NDArray[np.uint8] | None = None
        self._frame_lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._capture_display: display.Display | None = None
        self._window_invalid = False
        self._capture_times: list[float] = []  # Recent capture times in ms
        self._warning_shown = False

    def start(self):
        """Start the capture stream in background."""
        # Log capture configuration (window title already logged by WindowCapture)
        logger.info(
            "capture config",
            display_server=_get_display_server_info(),
            interval_ms=int(self._capture_interval * 1000),
        )

        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    @property
    def window_invalid(self) -> bool:
        """Check if the window ID is invalid (window was destroyed)."""
        return self._window_invalid

    def _capture_loop(self):
        """Background thread that captures frames continuously."""
        # Create dedicated display connection for thread-safety
        self._capture_display = display.Display()

        try:
            while self._running and not self._window_invalid:
                # Measure capture time
                start_time = time.perf_counter()
                frame = self._capture_frame()
                capture_time_ms = (time.perf_counter() - start_time) * 1000

                if frame is not None:
                    with self._frame_lock:
                        self._latest_frame = frame

                    # Track capture times and check for slow capture
                    # frame.shape is (height, width, channels)
                    self._check_capture_performance(capture_time_ms, (frame.shape[1], frame.shape[0]))

                time.sleep(self._capture_interval)
        finally:
            # Cleanup - always runs even if exception occurs
            if self._capture_display:
                try:
                    self._capture_display.close()
                except Exception:
                    pass
                self._capture_display = None

    def _check_capture_performance(self, capture_time_ms: float, frame_size: tuple[int, int]):
        """Check capture performance and warn if too slow.

        Args:
            capture_time_ms: Time taken for the last capture in milliseconds.
            frame_size: Tuple of (width, height) of the captured frame.
        """
        # Log on first successful capture
        if len(self._capture_times) == 0:
            width, height = frame_size
            logger.info("capture started", window_id=hex(self._window_id), resolution=f"{width}x{height}")

        # Only sample the first few frames
        if len(self._capture_times) < self.CAPTURE_TIME_SAMPLE_COUNT:
            self._capture_times.append(capture_time_ms)

        # Check after we have enough samples
        if len(self._capture_times) == self.CAPTURE_TIME_SAMPLE_COUNT and not self._warning_shown:
            avg_time = sum(self._capture_times) / len(self._capture_times)

            if avg_time > self.CAPTURE_TIME_WARNING_MS:
                self._warning_shown = True
                width, height = frame_size
                pixels = width * height
                megapixels = pixels / 1_000_000

                logger.warning(
                    "slow capture detected",
                    avg_capture_ms=int(avg_time),
                    resolution=f"{width}x{height}",
                    megapixels=f"{megapixels:.1f}MP",
                    hint="High resolution capture causes game stuttering. "
                    "Consider: (1) Run game in windowed mode at lower resolution, "
                    "(2) Lower display resolution, or (3) Increase capture interval in config.",
                )

    def _capture_frame(self) -> NDArray[np.uint8] | None:
        """Capture a single frame using the thread's display connection."""
        if self._capture_display is None:
            return None

        disp = self._capture_display

        try:
            window = disp.create_resource_object("window", self._window_id)

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

            geom = target_window.get_geometry()
            width = geom.width
            height = geom.height
            depth = geom.depth

            if width <= 0 or height <= 0:
                return None

            raw = target_window.get_image(0, 0, width, height, X.ZPixmap, 0xFFFFFFFF)

            # Convert raw pixel data to numpy BGRA array
            frame = _raw_to_numpy(raw.data, width, height, depth)
            if frame is None:
                return None

            return _crop_title_bar_if_needed(frame, self._window_id, crop_title_bar)

        except (BadDrawable, BadWindow):
            self._window_invalid = True
            with self._frame_lock:
                self._latest_frame = None
            return None
        except Exception:
            return None

    def get_frame(self) -> NDArray[np.uint8] | None:
        """Get the latest captured frame (non-blocking).

        Returns:
            Numpy array (H, W, 4) in BGRA format, or None if no frame available.
        """
        with self._frame_lock:
            return self._latest_frame

    def stop(self):
        """Stop the capture stream."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        self._thread = None
