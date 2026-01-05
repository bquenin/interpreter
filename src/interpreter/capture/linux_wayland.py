"""Wayland window capture using xdg-desktop-portal and PipeWire.

This module provides Wayland-native window capture for applications that don't
run through XWayland. It uses:
- xdg-desktop-portal ScreenCast API for window selection
- PipeWire via GStreamer for frame capture

The portal approach requires user interaction (a window picker dialog), but
works with all Wayland compositors that support the ScreenCast portal
(GNOME, KDE Plasma, etc.).
"""

import os
import re
import threading
import uuid
from collections.abc import Callable

import numpy as np
from numpy.typing import NDArray

from .. import log

logger = log.get_logger()

# Lazy imports for optional dependencies
_dbus = None
_gi = None
_Gst = None
_GLib = None


def _ensure_imports():
    """Lazily import dbus and GStreamer dependencies."""
    global _dbus, _gi, _Gst, _GLib

    if _dbus is not None:
        return True

    try:
        import dbus
        import gi
        from dbus.mainloop.glib import DBusGMainLoop

        gi.require_version("Gst", "1.0")
        from gi.repository import GLib, Gst

        # Initialize GStreamer
        Gst.init(None)

        # Set up DBus mainloop integration
        DBusGMainLoop(set_as_default=True)

        _dbus = dbus
        _gi = gi
        _Gst = Gst
        _GLib = GLib

        return True
    except ImportError as e:
        logger.warning("wayland capture dependencies not available", error=str(e))
        return False
    except Exception as e:
        logger.warning("failed to initialize wayland capture", error=str(e))
        return False


def is_wayland_available() -> bool:
    """Check if Wayland portal capture is available.

    Returns:
        True if running on Wayland with portal support, False otherwise.
    """
    # Must have WAYLAND_DISPLAY set
    if not os.environ.get("WAYLAND_DISPLAY"):
        return False

    if not _ensure_imports():
        return False

    try:
        bus = _dbus.SessionBus()
        bus.get_object("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop")
        return True
    except Exception:
        return False


class WaylandPortalCapture:
    """Handles xdg-desktop-portal ScreenCast session for window selection.

    This class manages the DBus communication with the portal to:
    1. Create a screencast session
    2. Show a window picker dialog
    3. Obtain a PipeWire stream for the selected window
    """

    def __init__(self):
        """Initialize the portal capture handler."""
        if not _ensure_imports():
            raise RuntimeError("Wayland capture dependencies not available")

        self._bus = _dbus.SessionBus()
        self._portal = self._bus.get_object(
            "org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop"
        )
        self._session_path: str | None = None
        self._streams: list | None = None
        self._pipewire_fd: int | None = None
        self._callback: Callable[[bool], None] | None = None

        # Get sender name for request/session paths
        sender = self._bus.get_unique_name()
        self._sender_name = re.sub(r"\.", r"_", sender[1:])

    def _new_token(self) -> str:
        """Generate a unique token for portal requests."""
        return f"t{uuid.uuid4().hex[:8]}"

    def _new_request_path(self) -> tuple[str, str]:
        """Generate a new request path and token."""
        token = self._new_token()
        path = f"/org/freedesktop/portal/desktop/request/{self._sender_name}/{token}"
        return path, token

    def _new_session_path(self) -> tuple[str, str]:
        """Generate a new session path and token."""
        token = self._new_token()
        path = f"/org/freedesktop/portal/desktop/session/{self._sender_name}/{token}"
        return path, token

    def select_window(self, callback: Callable[[bool], None]) -> None:
        """Start the portal flow to select a window.

        This shows a system window picker dialog. When the user selects a window
        (or cancels), the callback is called with True (success) or False (cancelled/error).

        Args:
            callback: Function called with True on success, False on cancel/error.
        """
        self._callback = callback
        self._create_session()

    def _create_session(self) -> None:
        """Step 1: Create a screencast session."""
        _, session_token = self._new_session_path()
        request_path, request_token = self._new_request_path()

        # Register response handler
        self._bus.add_signal_receiver(
            self._on_create_session_response,
            "Response",
            "org.freedesktop.portal.Request",
            "org.freedesktop.portal.Desktop",
            request_path,
        )

        options = {
            "handle_token": request_token,
            "session_handle_token": session_token,
        }

        try:
            self._portal.CreateSession(
                options, dbus_interface="org.freedesktop.portal.ScreenCast"
            )
            logger.debug("portal session creation requested")
        except Exception as e:
            logger.error("failed to create portal session", error=str(e))
            self._finish(False)

    def _on_create_session_response(self, response: int, results: dict) -> None:
        """Handle CreateSession response."""
        if response != 0:
            logger.warning("portal session creation failed", response=response)
            self._finish(False)
            return

        self._session_path = str(results.get("session_handle", ""))
        logger.debug("portal session created", session=self._session_path)
        self._select_sources()

    def _select_sources(self) -> None:
        """Step 2: Configure source selection (window capture)."""
        if not self._session_path:
            self._finish(False)
            return

        request_path, request_token = self._new_request_path()

        self._bus.add_signal_receiver(
            self._on_select_sources_response,
            "Response",
            "org.freedesktop.portal.Request",
            "org.freedesktop.portal.Desktop",
            request_path,
        )

        options = {
            "handle_token": request_token,
            "types": _dbus.UInt32(2),  # 2 = WINDOW (1 = MONITOR, 3 = BOTH)
            "multiple": False,
            "cursor_mode": _dbus.UInt32(1),  # 1 = Hidden, 2 = Embedded, 4 = Metadata
        }

        try:
            self._portal.SelectSources(
                self._session_path,
                options,
                dbus_interface="org.freedesktop.portal.ScreenCast",
            )
            logger.debug("portal source selection requested")
        except Exception as e:
            logger.error("failed to select sources", error=str(e))
            self._finish(False)

    def _on_select_sources_response(self, response: int, results: dict) -> None:
        """Handle SelectSources response."""
        if response != 0:
            logger.warning("portal source selection failed", response=response)
            self._finish(False)
            return

        logger.debug("portal sources configured")
        self._start_session()

    def _start_session(self) -> None:
        """Step 3: Start the session (shows window picker dialog)."""
        if not self._session_path:
            self._finish(False)
            return

        request_path, request_token = self._new_request_path()

        self._bus.add_signal_receiver(
            self._on_start_response,
            "Response",
            "org.freedesktop.portal.Request",
            "org.freedesktop.portal.Desktop",
            request_path,
        )

        options = {"handle_token": request_token}

        try:
            self._portal.Start(
                self._session_path,
                "",  # parent_window (empty = no parent)
                options,
                dbus_interface="org.freedesktop.portal.ScreenCast",
            )
            logger.debug("portal start requested, window picker should appear")
        except Exception as e:
            logger.error("failed to start portal session", error=str(e))
            self._finish(False)

    def _on_start_response(self, response: int, results: dict) -> None:
        """Handle Start response (after user picks a window)."""
        if response != 0:
            if response == 1:
                logger.info("user cancelled window selection")
            else:
                logger.warning("portal start failed", response=response)
            self._finish(False)
            return

        streams = results.get("streams", [])
        if not streams:
            logger.warning("no streams returned from portal")
            self._finish(False)
            return

        self._streams = list(streams)
        node_id = self._streams[0][0]
        props = dict(self._streams[0][1]) if len(self._streams[0]) > 1 else {}

        logger.info(
            "window selected via portal",
            node_id=node_id,
            source_type=props.get("source_type"),
        )

        self._open_pipewire_remote()

    def _open_pipewire_remote(self) -> None:
        """Step 4: Get PipeWire file descriptor."""
        if not self._session_path:
            self._finish(False)
            return

        try:
            fd_object = self._portal.OpenPipeWireRemote(
                self._session_path,
                {},
                dbus_interface="org.freedesktop.portal.ScreenCast",
            )
            self._pipewire_fd = fd_object.take()
            logger.debug("pipewire fd obtained", fd=self._pipewire_fd)
            self._finish(True)
        except Exception as e:
            logger.error("failed to open pipewire remote", error=str(e))
            self._finish(False)

    def _finish(self, success: bool) -> None:
        """Complete the portal flow and call the callback."""
        # On failure, close the session to avoid "Sources already selected" errors
        if not success:
            self._close_session()

        if self._callback:
            callback = self._callback
            self._callback = None
            callback(success)

    def _close_session(self) -> None:
        """Close just the portal session (not the PipeWire fd)."""
        if self._session_path:
            try:
                session = self._bus.get_object(
                    "org.freedesktop.portal.Desktop", self._session_path
                )
                session.Close(dbus_interface="org.freedesktop.portal.Session")
                logger.debug("portal session closed", session=self._session_path)
            except Exception:
                pass
            self._session_path = None
        self._streams = None

    def get_stream_info(self) -> tuple[int, int] | None:
        """Get the PipeWire connection info for frame capture.

        Returns:
            Tuple of (fd, node_id) or None if not available.
        """
        if self._pipewire_fd is None or not self._streams:
            return None
        node_id = self._streams[0][0]
        return (self._pipewire_fd, node_id)

    def close(self) -> None:
        """Close the portal session and release resources."""
        self._close_session()

        if self._pipewire_fd is not None:
            try:
                os.close(self._pipewire_fd)
            except Exception:
                pass
            self._pipewire_fd = None


class WaylandCaptureStream:
    """PipeWire-based capture stream using GStreamer.

    This class captures frames from a PipeWire stream obtained via the portal.
    It matches the interface of LinuxCaptureStream for compatibility with
    the existing capture infrastructure.
    """

    def __init__(self, fd: int, node_id: int, capture_interval: float = 0.25):
        """Initialize the capture stream.

        Args:
            fd: PipeWire file descriptor from portal.
            node_id: PipeWire node ID for the stream.
            capture_interval: Target interval between frames (not strictly enforced).
        """
        if not _ensure_imports():
            raise RuntimeError("Wayland capture dependencies not available")

        self._fd = fd
        self._node_id = node_id
        self._capture_interval = capture_interval
        self._pipeline = None
        self._appsink = None
        self._latest_frame: NDArray[np.uint8] | None = None
        self._frame_lock = threading.Lock()
        self._running = False
        self._loop = None
        self._loop_thread = None
        self.window_invalid = False

    def start(self) -> None:
        """Start the GStreamer pipeline for frame capture."""
        if self._running:
            return

        # Build GStreamer pipeline
        # pipewiresrc -> videoconvert (to BGRA) -> videorate (limit fps) -> appsink
        fps = int(1.0 / self._capture_interval) if self._capture_interval > 0 else 4
        pipeline_str = (
            f"pipewiresrc fd={self._fd} path={self._node_id} do-timestamp=true ! "
            f"videoconvert ! video/x-raw,format=BGRA ! "
            f"videorate ! video/x-raw,framerate={fps}/1 ! "
            f"appsink name=sink emit-signals=true max-buffers=2 drop=true"
        )

        try:
            self._pipeline = _Gst.parse_launch(pipeline_str)
        except Exception as e:
            logger.error("failed to create gstreamer pipeline", error=str(e))
            self.window_invalid = True
            return

        # Get appsink and connect signal
        self._appsink = self._pipeline.get_by_name("sink")
        self._appsink.connect("new-sample", self._on_new_sample)

        # Monitor bus for errors
        bus = self._pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message::error", self._on_error)
        bus.connect("message::eos", self._on_eos)

        # Start pipeline
        ret = self._pipeline.set_state(_Gst.State.PLAYING)
        if ret == _Gst.StateChangeReturn.FAILURE:
            logger.error("failed to start gstreamer pipeline")
            self.window_invalid = True
            return

        self._running = True
        logger.info("wayland capture stream started", node_id=self._node_id, fps=fps)

        # Run GLib mainloop in background thread for signal handling
        self._loop = _GLib.MainLoop()
        self._loop_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._loop_thread.start()

    def _run_loop(self) -> None:
        """Run GLib mainloop in background thread."""
        try:
            self._loop.run()
        except Exception:
            pass

    def _on_new_sample(self, appsink) -> int:
        """Handle new frame from GStreamer pipeline."""
        sample = appsink.emit("pull-sample")
        if not sample:
            return _Gst.FlowReturn.OK

        caps = sample.get_caps()
        struct = caps.get_structure(0)
        width = struct.get_value("width")
        height = struct.get_value("height")

        buffer = sample.get_buffer()
        success, map_info = buffer.map(_Gst.MapFlags.READ)

        if not success:
            return _Gst.FlowReturn.ERROR

        try:
            # Copy frame data to numpy array (BGRA format)
            data = np.frombuffer(map_info.data, dtype=np.uint8).copy()
            frame = data.reshape((height, width, 4))

            with self._frame_lock:
                self._latest_frame = frame

        finally:
            buffer.unmap(map_info)

        return _Gst.FlowReturn.OK

    def _on_error(self, bus, message) -> None:
        """Handle GStreamer error message."""
        err, debug = message.parse_error()
        logger.error("gstreamer error", error=str(err), debug=debug)
        self.window_invalid = True

    def _on_eos(self, bus, message) -> None:
        """Handle end-of-stream (window closed)."""
        logger.info("wayland capture stream ended (window closed)")
        self.window_invalid = True

    def get_frame(self) -> NDArray[np.uint8] | None:
        """Get the latest captured frame.

        Returns:
            Numpy array (H, W, 4) in BGRA format, or None if no frame available.
        """
        with self._frame_lock:
            if self._latest_frame is None:
                return None
            return self._latest_frame.copy()

    def stop(self) -> None:
        """Stop the capture stream and release resources."""
        self._running = False

        if self._loop:
            self._loop.quit()
            self._loop = None

        if self._pipeline:
            self._pipeline.set_state(_Gst.State.NULL)
            self._pipeline = None

        self._appsink = None
        self._latest_frame = None

        logger.debug("wayland capture stream stopped")

    def is_window_closed(self) -> bool:
        """Check if the captured window was closed.

        Returns:
            True if the window/stream is no longer valid.
        """
        return self.window_invalid
