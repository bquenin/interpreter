"""Platform-agnostic screen capture interface."""

import platform
from typing import Optional

from PIL import Image

# Import platform-specific implementation
_system = platform.system()

if _system == "Darwin":
    from .macos import find_window_by_title, capture_window, get_window_list, get_display_bounds_for_window, _get_window_bounds, MacOSCaptureStream
    CaptureStream = MacOSCaptureStream
    def get_content_offset(window_id: int) -> tuple[int, int]:
        return (0, 0)  # macOS handles this differently
elif _system == "Windows":
    from .windows import find_window_by_title, capture_window, get_window_list, _get_window_bounds, WindowsCaptureStream
    CaptureStream = WindowsCaptureStream
    def get_display_bounds_for_window(window_id: int) -> Optional[dict]:
        return None
    def get_content_offset(window_id: int) -> tuple[int, int]:
        return (0, 0)
elif _system == "Linux":
    from .linux import find_window_by_title, capture_window, get_window_list, _get_window_bounds, LinuxCaptureStream, get_display_bounds_for_window, get_content_offset
    CaptureStream = LinuxCaptureStream
else:
    raise RuntimeError(f"Unsupported platform: {_system}")


class WindowCapture:
    """Captures screenshots of a specific window by title."""

    def __init__(self, window_title: str):
        """Initialize the window capture.

        Args:
            window_title: Partial title of the window to capture.
        """
        self.window_title = window_title
        self._window_id: Optional[int] = None
        self._last_bounds: Optional[dict] = None
        self._stream: Optional[CaptureStream] = None

    def find_window(self) -> bool:
        """Find and cache the window ID.

        Returns:
            True if window was found, False otherwise.
        """
        window = find_window_by_title(self.window_title)
        if window:
            self._window_id = window["id"]
            self._last_bounds = window["bounds"]
            return True
        return False

    def capture(self) -> Optional[Image.Image]:
        """Capture a screenshot of the target window.

        Returns:
            PIL Image of the window, or None if capture failed.
        """
        # Try to find window if we don't have an ID yet
        if self._window_id is None:
            if not self.find_window():
                return None

        # Capture the window
        image = capture_window(self._window_id)

        # If capture failed, the window might have been closed
        # Try to find it again
        if image is None:
            self._window_id = None
            if self.find_window():
                image = capture_window(self._window_id)

        # Update bounds (window may have moved)
        if image is not None and self._window_id is not None:
            self._refresh_bounds()

        return image

    def _refresh_bounds(self) -> None:
        """Refresh the cached window bounds."""
        if self._window_id is None:
            return
        # Get updated bounds directly by window ID (more efficient)
        bounds = _get_window_bounds(self._window_id)
        if bounds:
            self._last_bounds = bounds

    @property
    def window_found(self) -> bool:
        """Check if the target window has been found."""
        return self._window_id is not None

    @property
    def bounds(self) -> Optional[dict]:
        """Get the bounds of the target window."""
        return self._last_bounds

    def get_display_bounds(self) -> Optional[dict]:
        """Get the bounds of the display containing the target window."""
        if self._window_id is None:
            return None
        return get_display_bounds_for_window(self._window_id)

    def get_content_offset(self) -> tuple[int, int]:
        """Get the offset of the content area within the window.

        On Linux, windows may have toolbars/decorations that are not captured.
        This returns the offset from window origin to where the actual content starts.

        Returns:
            Tuple of (x_offset, y_offset) in pixels.
        """
        if self._window_id is None:
            return (0, 0)
        return get_content_offset(self._window_id)

    @staticmethod
    def list_windows() -> list[dict]:
        """List all available windows.

        Returns:
            List of window dictionaries with id, title, and bounds.
        """
        return get_window_list()

    def start_stream(self) -> bool:
        """Start the background capture stream.

        Returns:
            True if stream started successfully, False otherwise.
        """
        # Find window first if needed
        if self._window_id is None:
            if not self.find_window():
                return False

        # Create platform-specific stream
        if _system == "Windows":
            # Windows uses window title for capture
            self._stream = CaptureStream(self.window_title)
        else:
            # macOS and Linux use window ID for capture
            self._stream = CaptureStream(self._window_id)

        self._stream.start()
        return True

    def get_frame(self) -> Optional[Image.Image]:
        """Get the latest frame from the capture stream.

        Returns:
            PIL Image of the window, or None if no frame available.
        """
        if self._stream is None:
            return None

        frame = self._stream.get_frame()

        # Update bounds if we got a frame
        if frame is not None and self._window_id is not None:
            self._refresh_bounds()

        return frame

    def stop_stream(self):
        """Stop the background capture stream."""
        if self._stream is not None:
            self._stream.stop()
            self._stream = None
