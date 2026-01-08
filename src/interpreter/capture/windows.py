"""Windows-specific window capture using Win32 API.

Uses PrintWindow API to capture window content even when obscured by other windows.
"""

import ctypes
import sys
import threading
import time
from ctypes import wintypes

import numpy as np
from numpy.typing import NDArray

from .convert import bgra_to_rgb_pil

# Fixed capture interval (4 FPS) - throttle Windows Graphics Capture API
CAPTURE_INTERVAL = 0.25

# Windows build number requirements for Graphics Capture API features
# - Build 18362 (Win10 1903): Basic Windows Graphics Capture API
# - Build 22000 (Win11): IsBorderRequired property to disable yellow border
MIN_BUILD_GRAPHICS_CAPTURE = 18362
MIN_BUILD_BORDER_TOGGLE = 22000


def get_content_offset(window_id: int) -> tuple[int, int]:
    """Get the offset of the content area within a window.

    On Windows, the overlay is positioned at the client area and the capture
    also covers the client area (after cropping title bar). So overlay and
    capture are aligned - no offset needed.

    Args:
        window_id: The window handle (HWND).

    Returns:
        Tuple of (x_offset, y_offset) in pixels. Always (0, 0) on Windows.
    """
    return (0, 0)


def get_windows_build() -> int:
    """Get the Windows build number.

    Returns:
        Windows build number (e.g., 22000 for Windows 11, 19045 for Windows 10 22H2).
        Returns 0 if detection fails or not on Windows.
    """
    if sys.platform != "win32":
        return 0

    try:
        # Use RtlGetVersion for accurate version (not subject to compatibility shims)
        # GetVersionEx can return wrong values due to app manifest compatibility
        ntdll = ctypes.windll.ntdll

        class OSVERSIONINFOEXW(ctypes.Structure):
            _fields_ = [
                ("dwOSVersionInfoSize", wintypes.DWORD),
                ("dwMajorVersion", wintypes.DWORD),
                ("dwMinorVersion", wintypes.DWORD),
                ("dwBuildNumber", wintypes.DWORD),
                ("dwPlatformId", wintypes.DWORD),
                ("szCSDVersion", wintypes.WCHAR * 128),
                ("wServicePackMajor", wintypes.WORD),
                ("wServicePackMinor", wintypes.WORD),
                ("wSuiteMask", wintypes.WORD),
                ("wProductType", wintypes.BYTE),
                ("wReserved", wintypes.BYTE),
            ]

        version_info = OSVERSIONINFOEXW()
        version_info.dwOSVersionInfoSize = ctypes.sizeof(OSVERSIONINFOEXW)
        ntdll.RtlGetVersion(ctypes.byref(version_info))
        return version_info.dwBuildNumber
    except Exception:
        return 0


def get_windows_version_string() -> str:
    """Get a human-readable Windows version string.

    Returns:
        Version string like 'Windows 11 (build 22000)' or 'Windows 10 (build 19045)'.
    """
    build = get_windows_build()
    if build == 0:
        return "Unknown"

    # Windows 11 starts at build 22000
    if build >= 22000:
        return f"Windows 11 (build {build})"
    else:
        return f"Windows 10 (build {build})"


def get_window_style_flags(hwnd: int) -> str:
    """Get window style flags for diagnostic logging.

    Args:
        hwnd: The window handle (HWND).

    Returns:
        String describing the window style flags (e.g., "POPUP+TOPMOST" or "CAPTION").
    """
    user32 = ctypes.windll.user32

    GWL_STYLE = -16
    GWL_EXSTYLE = -20

    style = user32.GetWindowLongW(hwnd, GWL_STYLE)
    exstyle = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)

    # Key style flags that affect capture
    flags = []
    if style & 0x80000000:  # WS_POPUP
        flags.append("POPUP")
    if style & 0x00C00000:  # WS_CAPTION
        flags.append("CAPTION")
    if exstyle & 0x00000008:  # WS_EX_TOPMOST
        flags.append("TOPMOST")
    if exstyle & 0x08000000:  # WS_EX_NOREDIRECTIONBITMAP
        flags.append("NOREDIRECT")

    return "+".join(flags) if flags else "NORMAL"


# Windows-specific imports
try:
    import pygetwindow as gw

    WINDOWS_AVAILABLE = True
except ImportError:
    WINDOWS_AVAILABLE = False

# Win32 API constants
DIB_RGB_COLORS = 0
BI_RGB = 0
PW_RENDERFULLCONTENT = 2  # Capture even if window is layered/composited

# System metrics constants
SM_CYCAPTION = 4  # Title bar height
SM_CYFRAME = 33  # Window frame height
SM_CXPADDEDBORDER = 92  # Padded border width (Vista+)


def get_title_bar_height() -> int:
    """Get the system title bar height in screen pixels.

    Uses GetSystemMetrics to get the actual title bar height for the current
    Windows theme and DPI setting.

    Returns:
        Title bar height in screen pixels.
    """
    user32 = ctypes.windll.user32
    # SM_CYCAPTION gives the title bar height
    caption_height = user32.GetSystemMetrics(SM_CYCAPTION)
    # SM_CYFRAME gives the window frame thickness
    frame_height = user32.GetSystemMetrics(SM_CYFRAME)
    # SM_CXPADDEDBORDER gives extra padding (Windows Vista+)
    padded_border = user32.GetSystemMetrics(SM_CXPADDEDBORDER)

    # Total non-client area at top = caption + frame + padded border
    return caption_height + frame_height + padded_border


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", wintypes.DWORD * 3),
    ]


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
            windows.append(
                {
                    "id": win._hWnd,
                    "title": win.title,
                    "owner": "",
                    "bounds": {
                        "x": win.left,
                        "y": win.top,
                        "width": win.width,
                        "height": win.height,
                    },
                }
            )
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


class RECT(ctypes.Structure):
    """Windows RECT structure."""

    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class POINT(ctypes.Structure):
    """Windows POINT structure."""

    _fields_ = [
        ("x", wintypes.LONG),
        ("y", wintypes.LONG),
    ]


def _get_window_bounds(window_id: int) -> dict | None:
    """Get the current bounds of a window (full window including chrome).

    Args:
        window_id: The window handle (HWND).

    Returns:
        Dictionary with x, y, width, height or None if failed.
    """
    rect = RECT()
    user32 = ctypes.windll.user32
    if user32.GetWindowRect(window_id, ctypes.byref(rect)):
        return {
            "x": rect.left,
            "y": rect.top,
            "width": rect.right - rect.left,
            "height": rect.bottom - rect.top,
        }
    return None


def is_window_foreground(window_id: int) -> bool:
    """Check if the specified window is the foreground window.

    Args:
        window_id: The window handle (HWND).

    Returns:
        True if the window is in foreground, False otherwise.
    """
    user32 = ctypes.windll.user32
    foreground_hwnd = user32.GetForegroundWindow()
    return foreground_hwnd == window_id


def _get_client_bounds(window_id: int) -> dict | None:
    """Get the client area bounds (content without title bar/borders).

    Args:
        window_id: The window handle (HWND).

    Returns:
        Dictionary with x, y, width, height in screen coordinates, or None if failed.
    """
    user32 = ctypes.windll.user32

    # Get client rect (in client coordinates, so left/top are 0)
    client_rect = RECT()
    if not user32.GetClientRect(window_id, ctypes.byref(client_rect)):
        return None

    # Convert client (0,0) to screen coordinates
    point = POINT(0, 0)
    if not user32.ClientToScreen(window_id, ctypes.byref(point)):
        return None

    return {
        "x": point.x,
        "y": point.y,
        "width": client_rect.right,  # client_rect.left is always 0
        "height": client_rect.bottom,  # client_rect.top is always 0
    }


def capture_window(window_id: int) -> NDArray[np.uint8] | None:
    """Capture a screenshot of a specific window's client area.

    Uses BitBlt from the window's DC (same approach as the Go 'captured' library).
    This captures the window content regardless of whether it's in the foreground.

    Args:
        window_id: The window handle (HWND).

    Returns:
        Numpy array (H, W, 4) in BGRA format, or None if capture failed.
    """
    # Get client area dimensions
    client_bounds = _get_client_bounds(window_id)
    if not client_bounds:
        return None

    width = client_bounds["width"]
    height = client_bounds["height"]

    if width <= 0 or height <= 0:
        return None

    # Get API functions
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    # Get the window's client area DC (not screen DC)
    # GetDC with hwnd returns DC for client area only
    hwnd_dc = user32.GetDC(window_id)
    if not hwnd_dc:
        return None

    try:
        # Create compatible DC and bitmap
        mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
        if not mem_dc:
            return None

        try:
            bitmap = gdi32.CreateCompatibleBitmap(hwnd_dc, width, height)
            if not bitmap:
                return None

            try:
                # Select bitmap into memory DC
                old_bitmap = gdi32.SelectObject(mem_dc, bitmap)

                # BitBlt from window DC (copies from client area origin 0,0)
                SRCCOPY = 0x00CC0020
                result = gdi32.BitBlt(mem_dc, 0, 0, width, height, hwnd_dc, 0, 0, SRCCOPY)

                if not result:
                    gdi32.SelectObject(mem_dc, old_bitmap)
                    return None

                # Prepare bitmap info for GetDIBits
                bmi = BITMAPINFO()
                bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
                bmi.bmiHeader.biWidth = width
                bmi.bmiHeader.biHeight = -height  # Negative for top-down
                bmi.bmiHeader.biPlanes = 1
                bmi.bmiHeader.biBitCount = 32
                bmi.bmiHeader.biCompression = BI_RGB

                # Create buffer for pixel data
                buffer_size = width * height * 4
                buffer = ctypes.create_string_buffer(buffer_size)

                # Get bitmap bits
                result = gdi32.GetDIBits(mem_dc, bitmap, 0, height, buffer, ctypes.byref(bmi), DIB_RGB_COLORS)

                gdi32.SelectObject(mem_dc, old_bitmap)

                if result == 0:
                    return None

                # Return raw BGRA numpy array (consumers convert on demand)
                arr = np.frombuffer(buffer, dtype=np.uint8).reshape((height, width, 4)).copy()
                return arr

            finally:
                gdi32.DeleteObject(bitmap)
        finally:
            gdi32.DeleteDC(mem_dc)
    finally:
        user32.ReleaseDC(window_id, hwnd_dc)


def _get_screen_size() -> tuple[int, int]:
    """Get the primary screen size in pixels."""
    user32 = ctypes.windll.user32
    # Get virtual screen size (accounts for DPI)
    width = user32.GetSystemMetrics(0)  # SM_CXSCREEN
    height = user32.GetSystemMetrics(1)  # SM_CYSCREEN
    return width, height


class MONITORINFO(ctypes.Structure):
    """Windows MONITORINFO structure."""

    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
    ]


def _get_monitor_size_for_window(window_id: int) -> tuple[int, int]:
    """Get the monitor size for the monitor containing the specified window.

    Args:
        window_id: The window handle (HWND).

    Returns:
        Tuple of (width, height) of the monitor, or primary screen size as fallback.
    """
    user32 = ctypes.windll.user32

    # Get the monitor that contains the window
    MONITOR_DEFAULTTONEAREST = 2
    hmonitor = user32.MonitorFromWindow(window_id, MONITOR_DEFAULTTONEAREST)

    if hmonitor:
        # Get monitor info
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(hmonitor, ctypes.byref(mi)):
            width = mi.rcMonitor.right - mi.rcMonitor.left
            height = mi.rcMonitor.bottom - mi.rcMonitor.top
            return width, height

    # Fallback to primary screen
    return _get_screen_size()


class WindowsCaptureStream:
    """Continuous window capture using Windows Graphics Capture API.

    Uses the windows-capture library which wraps the Windows Graphics Capture API.
    This can capture DirectX/OpenGL content even when the window is in the background.
    Throttled to 4 FPS to avoid wasteful high-frequency capture.
    """

    def __init__(self, window_id: int):
        """Initialize the capture stream.

        Args:
            window_id: The window handle (HWND) to capture.
        """
        self._window_id = window_id
        self._latest_frame: NDArray[np.uint8] | None = None
        self._frame_lock = threading.Lock()
        self._capture = None
        self._running = False
        self._last_frame_time: float = 0.0  # For 4 FPS throttling

    def start(self):
        """Start the capture stream in background.

        Raises:
            RuntimeError: If Windows version doesn't support Graphics Capture API.
        """
        from windows_capture import Frame, InternalCaptureControl, WindowsCapture

        # Check Windows version for Graphics Capture API support
        build = get_windows_build()
        if build < MIN_BUILD_GRAPHICS_CAPTURE:
            raise RuntimeError(
                f"Windows Graphics Capture API requires Windows 10 version 1903 or later "
                f"(build {MIN_BUILD_GRAPHICS_CAPTURE}+). Your system is build {build}. "
                f"Please update Windows to use this application."
            )

        # Determine border setting based on Windows version
        # - Windows 11 (build 22000+): Can disable border with draw_border=False
        # - Windows 10 1903-21H2: Must use draw_border=None (yellow border will appear)
        if build >= MIN_BUILD_BORDER_TOGGLE:
            draw_border = False  # Disable yellow capture border
        else:
            draw_border = None  # Skip border config (yellow border will appear)

        self._running = True
        self._last_frame_time = 0.0  # Reset throttling
        self._first_frame_logged = False  # Track if we've logged first frame

        # Log capture configuration
        from .. import log

        logger = log.get_logger()
        window_style = get_window_style_flags(self._window_id)
        logger.info(
            "capture started (hwnd)",
            hwnd=hex(self._window_id),
            draw_border=draw_border,
            window_style=window_style,
        )

        # Create capture instance using HWND (more reliable than window_name for dynamic titles)
        self._capture = WindowsCapture(
            cursor_capture=False,
            draw_border=draw_border,
            window_hwnd=self._window_id,
        )

        # Reference to self for use in callback
        stream = self

        # Set up frame handler
        @self._capture.event
        def on_frame_arrived(frame: Frame, capture_control: InternalCaptureControl):
            if not stream._running:
                capture_control.stop()
                return

            # Throttle to 4 FPS - skip frames that arrive too quickly
            now = time.time()
            if now - stream._last_frame_time < CAPTURE_INTERVAL:
                return
            stream._last_frame_time = now

            try:
                # Detect fullscreen: if frame fills the monitor, don't crop title bar
                # Use the monitor the window is on, not just the primary screen
                if stream._window_id:
                    screen_w, screen_h = _get_monitor_size_for_window(stream._window_id)
                else:
                    screen_w, screen_h = _get_screen_size()
                is_fullscreen = frame.width >= screen_w and frame.height >= screen_h

                # Log first frame info
                if not stream._first_frame_logged:
                    stream._first_frame_logged = True
                    from .. import log

                    log.get_logger().info(
                        "first frame received",
                        resolution=f"{frame.width}x{frame.height}",
                        fullscreen=is_fullscreen,
                    )

                # Crop out title bar only if not fullscreen
                if not is_fullscreen:
                    # Get title bar height in screen pixels
                    title_bar_screen = get_title_bar_height()
                    # Get window bounds to calculate the actual scale
                    # (frame size vs window size, not screen size)
                    window_bounds = _get_window_bounds(stream._window_id) if stream._window_id else None
                    if window_bounds and window_bounds["width"] > 0:
                        scale = frame.width / window_bounds["width"]
                    else:
                        scale = 1.0
                    # Convert to capture pixels
                    title_bar_px = int(title_bar_screen * scale)
                    if frame.height > title_bar_px:
                        frame = frame.crop(0, title_bar_px, frame.width, frame.height)

                # Get frame buffer (numpy array, shape: height x width x 4, BGRA format)
                arr = frame.frame_buffer

                # Save first frame for debugging (only once, only in debug mode)
                if not hasattr(stream, "_debug_frame_saved"):
                    stream._debug_frame_saved = True
                    from .. import log

                    if log.is_debug_enabled():
                        try:
                            debug_img = bgra_to_rgb_pil(arr)
                            debug_path = "debug_capture.png"
                            debug_img.save(debug_path)
                            log.get_logger().info("saved debug frame", path=debug_path)
                        except Exception as e:
                            log.get_logger().warning("failed to save debug frame", error=str(e))

                # Store raw BGRA numpy array (consumers convert on demand)
                with stream._frame_lock:
                    stream._latest_frame = arr.copy()
            except Exception as e:
                from .. import log

                log.get_logger().error("frame processing failed", error=str(e))

        @self._capture.event
        def on_closed():
            stream._running = False

        # Start capture in free-threaded mode (non-blocking)
        try:
            self._capture.start_free_threaded()
        except Exception as e:
            error_msg = str(e).strip()
            if not error_msg:
                # windows-capture sometimes throws empty exceptions
                raise RuntimeError(
                    f"Failed to start screen capture for window {hex(self._window_id)}. "
                    f"This can happen if the window uses exclusive fullscreen or a video driver "
                    f"that bypasses Windows Desktop Window Manager (DWM).\n\n"
                    f"Troubleshooting tips:\n"
                    f"  - Try running the application in windowed or borderless windowed mode\n"
                    f"  - For emulators: switch video driver to 'gl', 'glcore', or 'd3d11' (not 'vulkan' exclusive)\n"
                    f"  - Make sure the window is visible and not minimized\n"
                    f"  - Try running interpreter-v2 as Administrator"
                ) from e
            else:
                raise RuntimeError(f"Failed to start screen capture for window {hex(self._window_id)}: {error_msg}") from e

        # Wait for first frame to arrive (up to 5 seconds)
        for _ in range(100):
            with self._frame_lock:
                if self._latest_frame is not None:
                    break
            time.sleep(0.05)

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
        # The capture will stop on next frame via capture_control.stop()
