"""X11 capture must keep all requests on the caller's display connection."""

from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

pytest.importorskip("Xlib")

from interpreter.capture import linux_x11 as capture


@pytest.fixture
def x11(monkeypatch):
    """A window and its display; no running X server is needed."""
    frame = np.arange(240 * 320 * 4, dtype=np.uint8).reshape(240, 320, 4)
    window = Mock()
    window.get_attributes.return_value = SimpleNamespace(map_state=capture.X.IsViewable)
    window.query_tree.return_value = SimpleNamespace(children=[])
    window.get_geometry.return_value = SimpleNamespace(width=320, height=240, depth=24)
    window.get_image.return_value = SimpleNamespace(data=frame.tobytes())
    window.get_full_property.return_value = SimpleNamespace(value=[0, 0, 20, 0])
    root = Mock()
    root.translate_coords.return_value = SimpleNamespace(x=0, y=0)
    screen = SimpleNamespace(root=root, width_in_pixels=800, height_in_pixels=600)
    disp = Mock()
    disp.create_resource_object.return_value = window
    disp.screen.return_value = screen
    monkeypatch.setattr(capture, "_display", disp)
    return SimpleNamespace(display=disp, window=window, screen=screen, frame=frame)


@pytest.mark.parametrize("mode", ["decorated", "undecorated", "fullscreen"])
def test_stream_never_uses_the_ui_display(x11, monkeypatch, mode):
    """Exercise the real helper chain, including its nested bounds lookup."""
    if mode == "undecorated":
        x11.window.get_full_property.return_value = None
    elif mode == "fullscreen":
        x11.screen.width_in_pixels = 320
        x11.screen.height_in_pixels = 240

    ui_display = Mock(side_effect=AssertionError("capture accessed the UI display"))
    monkeypatch.setattr(capture, "_get_display", ui_display)
    stream = capture.LinuxCaptureStream(window_id=42)
    stream._capture_display = x11.display

    frame = stream._capture_frame()

    # _capture_frame catches exceptions, so explicitly check the forbidden access.
    ui_display.assert_not_called()
    expected = x11.frame[20:] if mode == "decorated" else x11.frame
    np.testing.assert_array_equal(frame, expected)


def test_stream_captures_content_child_without_cropping(x11, monkeypatch):
    child_frame = x11.frame[:120, :160]
    child = Mock()
    child.get_geometry.return_value = SimpleNamespace(x=5, y=20, width=160, height=120, depth=24)
    child.get_image.return_value = SimpleNamespace(data=child_frame.tobytes())
    x11.window.query_tree.return_value = SimpleNamespace(children=[child])
    ui_display = Mock(side_effect=AssertionError("capture accessed the UI display"))
    monkeypatch.setattr(capture, "_get_display", ui_display)
    stream = capture.LinuxCaptureStream(window_id=42)
    stream._capture_display = x11.display

    frame = stream._capture_frame()

    ui_display.assert_not_called()
    np.testing.assert_array_equal(frame, child_frame)


def test_ui_helpers_and_single_capture_use_the_default_display(x11):
    """The platform-neutral API still works without an explicit connection."""
    assert capture._get_window_bounds(42) == {"x": 0, "y": 0, "width": 320, "height": 240}
    assert capture.get_content_offset(42) == (0, 20)
    np.testing.assert_array_equal(capture.capture_window(42), x11.frame[20:])
