"""Platform-agnostic screen capture interface."""

import platform
from typing import Optional

from PIL import Image

# Import platform-specific implementation
_system = platform.system()

if _system == "Darwin":
    from .capture_macos import find_window_by_title, capture_window, get_window_list, get_display_bounds_for_window
elif _system == "Windows":
    from .capture_windows import find_window_by_title, capture_window, get_window_list
    # Windows doesn't have display bounds function yet
    def get_display_bounds_for_window(window_id: int) -> Optional[dict]:
        return None
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

        return image

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

    @staticmethod
    def list_windows() -> list[dict]:
        """List all available windows.

        Returns:
            List of window dictionaries with id, title, and bounds.
        """
        return get_window_list()
