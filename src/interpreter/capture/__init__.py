"""Platform-agnostic screen capture interface."""

import platform
import time
from typing import Optional

from PIL import Image

from .. import log

logger = log.get_logger()

# Track when window became invalid for timing measurement
_invalid_time: float = 0

# Import platform-specific implementation
_system = platform.system()

if _system == "Darwin":
    from .macos import find_window_by_title, capture_window, get_window_list, get_display_bounds_for_window, _get_window_bounds, MacOSCaptureStream
    CaptureStream = MacOSCaptureStream
    def get_content_offset(window_id: int) -> tuple[int, int]:
        return (0, 0)  # macOS handles this differently
elif _system == "Windows":
    from .windows import find_window_by_title, capture_window, get_window_list, _get_window_bounds, _get_screen_size, get_title_bar_height, WindowsCaptureStream
    CaptureStream = WindowsCaptureStream
    def get_display_bounds_for_window(window_id: int) -> Optional[dict]:
        return None
    def get_content_offset(window_id: int) -> tuple[int, int]:
        # Windows capture crops the title bar when NOT in fullscreen mode
        # In fullscreen, no cropping happens, so offset should be (0, 0)
        bounds = _get_window_bounds(window_id)
        if bounds is None:
            # Default to windowed mode offset using actual system title bar height
            return (0, get_title_bar_height())

        screen_w, screen_h = _get_screen_size()
        # Check if window fills the screen (fullscreen)
        is_fullscreen = (
            bounds["x"] <= 0 and bounds["y"] <= 0 and
            bounds["width"] >= screen_w and bounds["height"] >= screen_h
        )

        if is_fullscreen:
            return (0, 0)  # No title bar cropping in fullscreen
        else:
            # Use actual system title bar height (in screen pixels)
            return (0, get_title_bar_height())
elif _system == "Linux":
    from .linux import find_window_by_title, capture_window, get_window_list, _get_window_bounds, LinuxCaptureStream, get_display_bounds_for_window, get_content_offset
    CaptureStream = LinuxCaptureStream
else:
    raise RuntimeError(f"Unsupported platform: {_system}")


class WindowCapture:
    """Captures screenshots of a specific window by title."""

    def __init__(self, window_title: str, capture_interval: float = 0.25, window_id: Optional[int] = None, bounds: Optional[dict] = None):
        """Initialize the window capture.

        Args:
            window_title: Partial title of the window to capture.
            capture_interval: Seconds between background captures (Linux only).
            window_id: Optional window ID to use directly (skips title search).
            bounds: Optional window bounds if window_id is provided.
        """
        self.window_title = window_title
        self._window_id: Optional[int] = window_id
        self._actual_title: Optional[str] = window_title if window_id else None
        self._last_bounds: Optional[dict] = bounds
        self._stream: Optional[CaptureStream] = None
        self._capture_interval = capture_interval

    def find_window(self) -> bool:
        """Find and cache the window ID.

        Returns:
            True if window was found, False otherwise.
        """
        # If we already have a window ID, just verify it's still valid
        if self._window_id is not None:
            bounds = _get_window_bounds(self._window_id)
            if bounds:
                self._last_bounds = bounds
                return True
            # Window ID no longer valid, fall through to search by title

        window = find_window_by_title(self.window_title)
        if window:
            self._window_id = window["id"]
            self._actual_title = window["title"]  # Store actual title for Windows capture
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
            # Windows uses exact window title for capture
            self._stream = CaptureStream(self._actual_title)
        elif _system == "Linux":
            # Linux uses background thread with configurable interval
            self._stream = CaptureStream(self._window_id, self._capture_interval)
        else:
            # macOS uses window ID for capture
            self._stream = CaptureStream(self._window_id)

        self._stream.start()
        return True

    def get_frame(self) -> Optional[Image.Image]:
        """Get the latest frame from the capture stream.

        Returns:
            PIL Image of the window, or None if no frame available.
        """
        global _invalid_time

        # No stream - try to find window and start one
        if self._stream is None:
            if self.find_window():
                logger.debug("window found, starting stream", window_id=self._window_id)
                self.start_stream()
            return None

        # Check if window became invalid (e.g., fullscreen transition)
        if hasattr(self._stream, 'window_invalid') and self._stream.window_invalid:
            _invalid_time = time.time()
            old_id = self._window_id
            logger.debug("window invalid, stopping stream", old_id=old_id)
            # Stop the broken stream immediately
            self._stream.stop()
            self._stream = None
            # Try to find new window and start stream
            if self.find_window():
                logger.debug("window found", old_id=old_id, new_id=self._window_id, changed=old_id != self._window_id)
                self.start_stream()
                logger.debug("stream restarted", window_id=self._window_id)
            else:
                logger.debug("window not found during recovery")
            return None  # No frame this iteration

        frame = self._stream.get_frame()

        # Double-check: window might have become invalid between our initial check and now
        if hasattr(self._stream, 'window_invalid') and self._stream.window_invalid:
            old_id = self._window_id
            logger.debug("window invalid after frame fetch, discarding", old_id=old_id)
            self._stream.stop()
            self._stream = None
            if self.find_window():
                logger.debug("window found", old_id=old_id, new_id=self._window_id)
                self.start_stream()
            return None  # Discard stale frame

        # Log recovery timing when we get first frame after window change
        if frame is not None and _invalid_time > 0:
            elapsed = time.time() - _invalid_time
            logger.debug("recovery complete", elapsed_ms=int(elapsed * 1000))
            _invalid_time = 0

        # Update bounds if we got a frame
        if frame is not None and self._window_id is not None:
            self._refresh_bounds()

        return frame

    @property
    def fps(self) -> float:
        """Get the current capture frame rate from the stream.

        Returns:
            Frames per second being captured, or 0.0 if no stream.
        """
        if self._stream is None:
            return 0.0
        if hasattr(self._stream, 'fps'):
            return self._stream.fps
        return 0.0

    def stop_stream(self):
        """Stop the background capture stream."""
        if self._stream is not None:
            self._stream.stop()
            self._stream = None
