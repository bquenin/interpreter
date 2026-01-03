"""Base classes and mixins for capture streams."""

import threading
import time


class FPSTrackerMixin:
    """Mixin class providing FPS tracking for capture streams.

    Provides consistent FPS calculation across all platforms.
    Updates FPS every second based on frame count.

    Usage:
        class MyCaptureStream(FPSTrackerMixin):
            def __init__(self):
                self._frame_lock = threading.Lock()
                self._init_fps_tracking()

            def start(self):
                self._reset_fps_tracking()
                # ... start capture ...

            def _on_frame_captured(self):
                with self._frame_lock:
                    self._update_fps()
    """

    _frame_count: int
    _fps: float
    _fps_update_time: float
    _frame_lock: threading.Lock

    def _init_fps_tracking(self) -> None:
        """Initialize FPS tracking variables. Call in __init__."""
        self._frame_count = 0
        self._fps = 0.0
        self._fps_update_time = time.time()

    def _reset_fps_tracking(self) -> None:
        """Reset FPS tracking. Call in start()."""
        self._frame_count = 0
        self._fps = 0.0
        self._fps_update_time = time.time()

    def _update_fps(self) -> None:
        """Update FPS counter. Call inside frame_lock after each frame."""
        self._frame_count += 1
        now = time.time()
        elapsed = now - self._fps_update_time
        if elapsed >= 1.0:
            self._fps = self._frame_count / elapsed
            self._frame_count = 0
            self._fps_update_time = now

    @property
    def fps(self) -> float:
        """Get the current capture frame rate.

        Returns:
            Frames per second being captured by the background thread.
        """
        with self._frame_lock:
            return self._fps
