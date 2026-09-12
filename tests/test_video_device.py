"""Tests for the video device capture source (format choice, frame conversion, config)."""

import numpy as np
import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtMultimedia import QVideoFrameFormat
from PySide6.QtWidgets import QApplication

from interpreter.capture.video_device import (
    MAX_FRAME_AREA,
    VideoDeviceCapture,
    choose_format,
    find_video_device,
    qimage_to_bgra,
)
from interpreter.config import Config


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class FakeFormat:
    """Stand-in for QCameraFormat (its constructor is not public)."""

    def __init__(self, width: int, height: int, fps: float, pixel_format=QVideoFrameFormat.PixelFormat.Format_NV12):
        self._size = QSize(width, height)
        self._fps = fps
        self._pixel_format = pixel_format

    def resolution(self) -> QSize:
        return self._size

    def maxFrameRate(self) -> float:
        return self._fps

    def pixelFormat(self):
        return self._pixel_format


MJPEG = QVideoFrameFormat.PixelFormat.Format_Jpeg


def test_choose_format_prefers_largest_resolution_up_to_1080p():
    formats = [
        FakeFormat(640, 480, 30),
        FakeFormat(3840, 2160, 60),
        FakeFormat(1920, 1080, 60),
        FakeFormat(1280, 720, 60),
    ]
    chosen = choose_format(formats)
    assert chosen.resolution() == QSize(1920, 1080)
    assert chosen.resolution().width() * chosen.resolution().height() <= MAX_FRAME_AREA


def test_choose_format_prefers_uncompressed_over_mjpeg_at_usable_fps():
    formats = [FakeFormat(1920, 1080, 60, MJPEG), FakeFormat(1920, 1080, 30)]
    assert choose_format(formats).pixelFormat() != MJPEG


def test_choose_format_skips_crawling_uncompressed_modes():
    """USB 2 cards expose 1080p YUY2 at 5 fps; MJPEG at 60 fps is the better mode."""
    formats = [FakeFormat(1920, 1080, 5, QVideoFrameFormat.PixelFormat.Format_YUYV), FakeFormat(1920, 1080, 60, MJPEG)]
    assert choose_format(formats).pixelFormat() == MJPEG


def test_choose_format_takes_the_higher_frame_rate_otherwise():
    formats = [FakeFormat(1920, 1080, 30), FakeFormat(1920, 1080, 60)]
    assert choose_format(formats).maxFrameRate() == 60


def test_choose_format_falls_back_to_smallest_oversized_mode():
    formats = [FakeFormat(3840, 2160, 30), FakeFormat(2560, 1440, 60)]
    assert choose_format(formats).resolution() == QSize(2560, 1440)


def test_choose_format_handles_no_formats():
    assert choose_format([]) is None


def test_qimage_to_bgra_returns_bgra_and_copies(qapp):
    image = QImage(5, 3, QImage.Format.Format_RGB32)
    image.fill(QColor(10, 20, 30))
    frame = qimage_to_bgra(image)
    assert frame.shape == (3, 5, 4)
    assert frame.dtype == np.uint8
    assert tuple(frame[0, 0]) == (30, 20, 10, 255)
    # The array must outlive the QImage
    del image
    assert tuple(frame[2, 4]) == (30, 20, 10, 255)


def test_qimage_to_bgra_handles_padded_rows(qapp):
    """Qt pads scanlines to 4 bytes; RGB888 with an odd width has a stride wider than width*3."""
    image = QImage(3, 2, QImage.Format.Format_RGB888)
    image.fill(QColor(1, 2, 3))
    frame = qimage_to_bgra(image)
    assert frame.shape == (2, 3, 4)
    assert tuple(frame[1, 2]) == (3, 2, 1, 255)


def test_find_video_device_unknown_name(qapp):
    assert find_video_device("no such capture card") is None


def test_video_device_capture_conforms_to_capture_protocol():
    """Static check: everything the GUI's frame loop calls on a capture source."""
    for attr in ("get_frame", "bounds", "window_invalid", "get_content_offset", "stop", "start"):
        assert hasattr(VideoDeviceCapture, attr)


def test_config_round_trips_video_device(tmp_path):
    path = tmp_path / "config.yml"
    config = Config(config_path=str(path))
    config.video_device = "Game Capture HD60 X"
    config.save()
    assert Config.load(str(path)).video_device == "Game Capture HD60 X"


def test_config_omits_empty_video_device(tmp_path):
    path = tmp_path / "config.yml"
    Config(config_path=str(path)).save()
    assert "video_device" not in path.read_text(encoding="utf-8")
    assert Config.load(str(path)).video_device == ""
