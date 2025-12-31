"""Windows-specific window capture using Win32 API.

Uses PrintWindow API to capture window content even when obscured by other windows.
"""

import ctypes
import threading
from ctypes import wintypes
from typing import Optional

from PIL import Image

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


def _get_window_bounds(window_id: int) -> Optional[dict]:
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


def _get_client_bounds(window_id: int) -> Optional[dict]:
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


def capture_window(window_id: int) -> Optional[Image.Image]:
    """Capture a screenshot of a specific window's client area.

    Uses BitBlt from the window's DC (same approach as the Go 'captured' library).
    This captures the window content regardless of whether it's in the foreground.

    Args:
        window_id: The window handle (HWND).

    Returns:
        PIL Image of the window's client area, or None if capture failed.
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
                result = gdi32.BitBlt(
                    mem_dc, 0, 0, width, height,
                    hwnd_dc, 0, 0, SRCCOPY
                )

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
                result = gdi32.GetDIBits(
                    mem_dc, bitmap, 0, height,
                    buffer, ctypes.byref(bmi), DIB_RGB_COLORS
                )

                gdi32.SelectObject(mem_dc, old_bitmap)

                if result == 0:
                    return None

                # Convert BGRA to RGB
                img = Image.frombuffer("RGBA", (width, height), buffer, "raw", "BGRA", 0, 1)
                return img.convert("RGB")

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


class WindowsCaptureStream:
    """Continuous window capture using Windows Graphics Capture API.

    Uses the windows-capture library which wraps the Windows Graphics Capture API.
    This can capture DirectX/OpenGL content even when the window is in the background.
    """

    # Title bar height to crop in captured pixels
    # At 200% DPI, a 32px logical title bar is ~64px in the capture
    # Using 70px to be safe
    TITLE_BAR_HEIGHT_PX = 70

    def __init__(self, window_title: str):
        """Initialize the capture stream.

        Args:
            window_title: Partial title of the window to capture.
        """
        self._window_title = window_title
        self._latest_frame: Optional[Image.Image] = None
        self._frame_lock = threading.Lock()
        self._capture = None
        self._running = False

    def start(self):
        """Start the capture stream in background."""
        from windows_capture import WindowsCapture, Frame, InternalCaptureControl
        import numpy as np

        self._running = True

        # Create capture instance
        self._capture = WindowsCapture(
            cursor_capture=False,
            draw_border=False,
            window_name=self._window_title,
        )

        # Reference to self for use in callback
        stream = self

        # Set up frame handler
        @self._capture.event
        def on_frame_arrived(frame: Frame, capture_control: InternalCaptureControl):
            if not stream._running:
                capture_control.stop()
                return

            try:
                # Detect fullscreen: if frame fills the screen, don't crop title bar
                screen_w, screen_h = _get_screen_size()
                is_fullscreen = (frame.width >= screen_w and frame.height >= screen_h)

                # Crop out title bar only if not fullscreen
                if not is_fullscreen:
                    title_bar_px = WindowsCaptureStream.TITLE_BAR_HEIGHT_PX
                    if frame.height > title_bar_px:
                        frame = frame.crop(0, title_bar_px, frame.width, frame.height)

                # Get frame buffer (numpy array, shape: height x width x 4, BGRA format)
                arr = frame.frame_buffer

                # Convert BGRA to RGB
                rgb = arr[:, :, [2, 1, 0]]  # Reorder channels: B,G,R,A -> R,G,B
                rgb = np.ascontiguousarray(rgb)  # Ensure C-contiguous for PIL

                img = Image.fromarray(rgb, mode="RGB")

                with stream._frame_lock:
                    stream._latest_frame = img
            except Exception:
                pass  # Silently ignore frame errors

        @self._capture.event
        def on_closed():
            stream._running = False

        # Start capture in free-threaded mode (non-blocking)
        self._capture.start_free_threaded()

        # Wait for first frame to arrive (up to 5 seconds)
        import time
        for _ in range(100):
            with self._frame_lock:
                if self._latest_frame is not None:
                    break
            time.sleep(0.05)

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
        # The capture will stop on next frame via capture_control.stop()
