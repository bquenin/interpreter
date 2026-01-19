"""Platform-agnostic screen capture interface."""

import os
import platform
import time
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from .. import log


class Capture(Protocol):
    """Unified interface for all capture implementations.

    Both WindowCapture (X11/macOS/Windows) and WaylandCaptureStream
    conform to this protocol, allowing platform-agnostic usage.
    """

    def get_frame(self) -> NDArray[np.uint8] | None:
        """Get the latest captured frame.

        Returns:
            Numpy array (H, W, 4) in BGRA format, or None if no frame available.
        """
        ...

    @property
    def bounds(self) -> dict | None:
        """Get window bounds (x, y, width, height).

        Returns None on Wayland where window positions aren't exposed.
        """
        ...

    @property
    def window_invalid(self) -> bool:
        """Check if capture target is no longer valid (e.g., window closed)."""
        ...

    def get_content_offset(self) -> tuple[int, int]:
        """Get the offset of content area within the window.

        Returns:
            Tuple of (x_offset, y_offset) in pixels. Always (0, 0) on Wayland.
        """
        ...

    def stop(self) -> None:
        """Stop capture and release resources."""
        ...

logger = log.get_logger()


# Track when window became invalid for timing measurement
_invalid_time: float = 0

# Import platform-specific implementation
_system = platform.system()

if _system == "Darwin":
    from .macos import (
        MacOSCaptureStream,
        _get_window_bounds,
        capture_window,
        find_window_by_title,
        get_content_offset,
        get_window_list,
    )

    CaptureStream = MacOSCaptureStream
    _is_wayland_session = False

    def is_window_foreground(window_id: int) -> bool:
        # TODO: Implement for macOS if needed
        return True
elif _system == "Windows":
    from .windows import (
        WindowsCaptureStream,
        _get_client_bounds,
        _get_window_bounds,
        capture_window,
        find_window_by_title,
        get_content_offset,
        get_window_list,
        is_window_foreground,
    )

    CaptureStream = WindowsCaptureStream
    _is_wayland_session = False
elif _system == "Linux":
    from pipewire_capture import is_available as _pipewire_available

    def _should_use_wayland_capture() -> bool:
        """Determine if Wayland/PipeWire capture should be used.

        Uses XDG_SESSION_TYPE as the primary indicator, with special handling
        for gamescope (Steam Deck Gaming Mode) which sets XDG_SESSION_TYPE=x11
        but requires portal-based capture.
        """
        session_type = os.getenv("XDG_SESSION_TYPE", "").lower()

        if session_type == "wayland":
            return True

        if session_type == "x11":
            # Gamescope (Steam Deck Gaming Mode) sets XDG_SESSION_TYPE=x11
            # but is actually a Wayland compositor that needs portal capture
            if os.getenv("XDG_CURRENT_DESKTOP", "").lower() == "gamescope":
                return True
            # Standard X11 session - use X11 capture unless gamescope env is set
            return bool(os.getenv("GAMESCOPE_WAYLAND_DISPLAY"))

        # Unknown/unset session type - fall back to portal availability check
        return _pipewire_available()

    _is_wayland_session = _should_use_wayland_capture()

    if _is_wayland_session:
        # Wayland session: use pipewire-capture
        # Import stubs for window enumeration (portal handles selection instead)
        from .linux_wayland import (
            WaylandCaptureStream,
            _get_window_bounds,
            find_window_by_title,
            get_content_offset,
            get_window_list,
        )

        CaptureStream = WaylandCaptureStream

        def capture_window(window_id: int):
            """Stub - Wayland uses portal-based capture instead."""
            return None

    else:
        # X11-only session: use python-xlib
        from .linux_x11 import (
            LinuxCaptureStream,
            _get_window_bounds,
            capture_window,
            find_window_by_title,
            get_content_offset,
            get_window_list,
        )

        CaptureStream = LinuxCaptureStream

    def is_window_foreground(window_id: int) -> bool:
        # TODO: Implement for Linux if needed
        return True
else:
    raise RuntimeError(f"Unsupported platform: {_system}")


class WindowCapture:
    """Captures screenshots of a specific window by title."""

    def __init__(
        self,
        window_title: str,
        capture_interval: float = 0.25,
        window_id: int | None = None,
        bounds: dict | None = None,
    ):
        """Initialize the window capture.

        Args:
            window_title: Partial title of the window to capture.
            capture_interval: Seconds between background captures (Linux only).
            window_id: Optional window ID to use directly (skips title search).
            bounds: Optional window bounds if window_id is provided.
        """
        self.window_title = window_title
        self._window_id: int | None = window_id
        self._actual_title: str | None = window_title if window_id else None
        self._last_bounds: dict | None = bounds
        self._stream: CaptureStream | None = None
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
                # Refresh with proper bounds (client bounds on Windows)
                self._refresh_bounds()
                return True
            # Window ID no longer valid, fall through to search by title

        window = find_window_by_title(self.window_title)
        if window:
            self._window_id = window["id"]
            self._actual_title = window["title"]  # Store actual title for Windows capture
            # Get proper bounds (client bounds on Windows)
            self._refresh_bounds()
            return True
        return False

    def capture(self) -> NDArray[np.uint8] | None:
        """Capture a screenshot of the target window.

        Returns:
            Numpy array (H, W, 4) in BGRA format, or None if capture failed.
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
        """Refresh the cached window bounds.

        On Windows, uses client bounds (content area without title bar) since
        the capture stream crops out the title bar. On macOS/Linux, uses full
        window bounds.
        """
        if self._window_id is None:
            return

        # On Windows, use client bounds since capture crops title bar
        if _system == "Windows":
            bounds = _get_client_bounds(self._window_id)
        else:
            bounds = _get_window_bounds(self._window_id)

        if bounds:
            self._last_bounds = bounds

    @property
    def window_found(self) -> bool:
        """Check if the target window has been found."""
        return self._window_id is not None

    @property
    def bounds(self) -> dict | None:
        """Get the bounds of the target window."""
        return self._last_bounds

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

    def is_foreground(self) -> bool:
        """Check if the target window is currently in the foreground.

        Returns:
            True if the window is the foreground window, False otherwise.
            Returns True if window_id is not set (fail-open for safety).
        """
        if self._window_id is None:
            return True
        return is_window_foreground(self._window_id)

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

        # Log window selection
        bounds = self._last_bounds or {}
        logger.info(
            "window selected",
            title=self._actual_title,
            window_id=self._window_id,
            width=bounds.get("width", 0),
            height=bounds.get("height", 0),
            x=bounds.get("x", 0),
            y=bounds.get("y", 0),
        )

        # Create platform-specific stream
        if _system == "Windows":
            # Windows uses HWND for reliable capture (immune to dynamic titles)
            self._stream = CaptureStream(self._window_id)
        elif _system == "Linux":
            # Linux uses background thread with configurable interval
            self._stream = CaptureStream(self._window_id, self._capture_interval)
        else:
            # macOS uses window ID for capture
            self._stream = CaptureStream(self._window_id)

        self._stream.start()
        return True

    def get_frame(self) -> NDArray[np.uint8] | None:
        """Get the latest frame from the capture stream.

        Returns:
            Numpy array (H, W, 4) in BGRA format, or None if no frame available.
        """
        global _invalid_time

        # No stream - try to find window and start one
        if self._stream is None:
            if self.find_window():
                logger.debug("window found, starting stream", window_id=self._window_id)
                self.start_stream()
            return None

        # Check if window became invalid (e.g., fullscreen transition)
        if hasattr(self._stream, "window_invalid") and self._stream.window_invalid:
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
        if hasattr(self._stream, "window_invalid") and self._stream.window_invalid:
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

    def stop_stream(self):
        """Stop the background capture stream."""
        if self._stream is not None:
            self._stream.stop()
            self._stream = None

    @property
    def window_invalid(self) -> bool:
        """Check if capture target is no longer valid.

        Delegates to the underlying stream's window_invalid property.
        Returns False if no stream is active.
        """
        if self._stream is None:
            return False
        return getattr(self._stream, "window_invalid", False)

    def stop(self) -> None:
        """Stop capture and release resources.

        Alias for stop_stream() to conform to Capture protocol.
        """
        self.stop_stream()
