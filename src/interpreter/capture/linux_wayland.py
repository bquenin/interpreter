"""Wayland window capture using pipewire-capture library.

This module provides Wayland-native window capture using:
- xdg-desktop-portal ScreenCast API for window selection
- PipeWire for frame capture

The pipewire-capture library ships pre-built wheels, avoiding the need for
system dependencies like Cairo/pycairo that caused installation issues on
Nobara, Steam Deck, and Arch Linux.
"""

import numpy as np
from numpy.typing import NDArray
from pipewire_capture import CaptureStream as PwCaptureStream
from pipewire_capture import PortalCapture, init_logging, is_available

from .. import log

logger = log.get_logger()


def is_wayland_available() -> bool:
    """Check if Wayland portal capture is available.

    Returns:
        True if running on Wayland with portal support, False otherwise.
    """
    return is_available()


def configure_logging(debug: bool) -> None:
    """Configure pipewire-capture logging level.

    Args:
        debug: If True, enable debug logging in pipewire-capture.
    """
    if debug:
        init_logging("debug")


def get_window_list() -> list[dict]:
    """Return empty list - Wayland uses portal picker instead of window enumeration."""
    return []


def find_window_by_title(title_substring: str) -> dict | None:
    """Return None - Wayland uses portal picker instead of title search."""
    return None


def _get_window_bounds(window_id: int) -> dict | None:
    """Return None - Wayland doesn't expose window bounds."""
    return None


def get_content_offset(window_id: int) -> tuple[int, int]:
    """Return (0, 0) - Wayland capture doesn't need content offset adjustment."""
    return (0, 0)


class WaylandPortalCapture:
    """Portal-based window selection for screen capture.

    Uses xdg-desktop-portal ScreenCast interface to show a system
    window picker dialog and obtain a PipeWire stream for the
    selected window.
    """

    def __init__(self):
        """Initialize the portal capture handler."""
        self._portal = PortalCapture()
        self._session = None  # PortalSession from select_window()

    def select_window(self) -> tuple[int, int, int, int] | None:
        """Show the system window picker and return stream info.

        This is a blocking operation that shows the system window picker dialog.

        Returns:
            Tuple of (fd, node_id, width, height) on success, or None if cancelled.

        Raises:
            Exception: If the portal flow fails.
        """
        # API changed in pipewire-capture 0.2.4 - returns PortalSession object
        self._session = self._portal.select_window()

        if self._session:
            logger.info(
                "window selected via portal",
                node_id=self._session.node_id,
                width=self._session.width,
                height=self._session.height,
            )
            return (self._session.fd, self._session.node_id, self._session.width, self._session.height)

        return None

    def get_stream_info(self) -> tuple[int, int, int, int] | None:
        """Get the PipeWire stream info after successful window selection.

        Returns:
            Tuple of (fd, node_id, width, height) or None if no stream is available.
        """
        if self._session:
            return (self._session.fd, self._session.node_id, self._session.width, self._session.height)
        return None

    def close(self) -> None:
        """Close the portal session and release resources."""
        logger.debug("closing portal capture")
        if self._session:
            self._session.close()
            self._session = None
        self._portal = None


class WaylandCaptureStream:
    """PipeWire-based capture stream.

    Captures frames from a PipeWire stream obtained via the portal.
    Frames are returned as numpy arrays in BGRA format.
    """

    def __init__(self, fd: int, node_id: int, width: int, height: int, capture_interval: float = 0.25):
        """Initialize the capture stream.

        Args:
            fd: PipeWire file descriptor from portal.
            node_id: PipeWire node ID for the stream.
            width: Initial width from portal.
            height: Initial height from portal.
            capture_interval: Target interval between frames in seconds.
        """
        self._stream = PwCaptureStream(fd, node_id, width, height, capture_interval)
        self._started = False

    def start(self) -> None:
        """Start the capture stream."""
        logger.info("starting wayland capture stream")
        self._stream.start()
        self._started = True

    def get_frame(self) -> NDArray[np.uint8] | None:
        """Get the latest captured frame.

        Returns:
            Numpy array (H, W, 4) in BGRA format, or None if no frame available.
        """
        if not self._started:
            return None
        return self._stream.get_frame()

    @property
    def bounds(self) -> dict | None:
        """Get window bounds.

        Returns:
            None - Wayland doesn't expose window positions.
        """
        return None

    @property
    def window_invalid(self) -> bool:
        """Check if the captured window has been closed.

        Returns:
            True if the window/stream is no longer valid.
        """
        return self._stream.window_invalid

    def get_content_offset(self) -> tuple[int, int]:
        """Get content offset within window.

        Returns:
            Always (0, 0) - Wayland capture doesn't need offset adjustment.
        """
        return (0, 0)

    def stop(self) -> None:
        """Stop the capture stream and release resources."""
        if self._started:
            logger.debug("stopping wayland capture stream")
            self._stream.stop()
            self._started = False
