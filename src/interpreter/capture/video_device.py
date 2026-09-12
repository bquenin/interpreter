"""Video device capture (capture cards, webcams) through Qt Multimedia.

Capture cards show up as standard UVC video devices, so this source reads from them the same
way it would read from a webcam. Qt's FFmpeg multimedia backend handles the platform camera
API (Media Foundation on Windows, AVFoundation on macOS, V4L2 on Linux) and ships inside the
PySide6 wheels, so no extra dependency is needed.

Unlike a window there is nothing on the desktop to anchor an overlay to: the game plays on a TV
through the card's passthrough. The source therefore reports no bounds and the GUI keeps the
translation in banner mode.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import QObject, Slot
from PySide6.QtGui import QImage
from PySide6.QtMultimedia import (
    QCamera,
    QCameraDevice,
    QCameraFormat,
    QMediaCaptureSession,
    QMediaDevices,
    QVideoFrame,
    QVideoFrameFormat,
    QVideoSink,
)

from .. import log

logger = log.get_logger()

# Frames larger than this are not worth decoding at the device's frame rate just to OCR a few
# frames a second; 1080p is plenty for text detection.
MAX_FRAME_AREA = 1920 * 1080

# Uncompressed modes below this frame rate (USB 2 cards often expose 1080p YUY2 at 5 fps)
# rank below an MJPEG mode at a usable rate.
MIN_UNCOMPRESSED_FPS = 10.0


def list_video_devices() -> list[QCameraDevice]:
    """Video input devices currently attached, in Qt's order (default device first)."""
    return list(QMediaDevices.videoInputs())


def device_id(device: QCameraDevice) -> str:
    """The device's unique id as text (a Media Foundation symbolic link, an AVFoundation unique
    id, or a /dev/video path). Tells two devices of the same model apart."""
    return bytes(device.id()).decode("utf-8", "replace")


def find_video_device(name: str, id_text: str = "") -> QCameraDevice | None:
    """Find an attached device, by unique id when one is given, else by description.

    The id wins when it is present: two cards of the same model share a description.
    The name is the fallback because ids can change on Linux (/dev/video numbering
    follows plug order) while the description stays put.
    """
    devices = list_video_devices()
    if id_text:
        for device in devices:
            if device_id(device) == id_text:
                return device
    for device in devices:
        if device.description() == name:
            return device
    return None


def _is_compressed(pixel_format: QVideoFrameFormat.PixelFormat) -> bool:
    return pixel_format == QVideoFrameFormat.PixelFormat.Format_Jpeg


def choose_format(formats: list[QCameraFormat]) -> QCameraFormat | None:
    """Pick the mode to open a device in.

    Largest resolution up to 1080p wins. Within a resolution, an uncompressed mode at a usable
    frame rate is preferred over MJPEG (no decoding), then the higher frame rate wins.
    Devices that only offer modes above 1080p fall back to the smallest of those.
    """
    if not formats:
        return None

    def key(fmt: QCameraFormat):
        size = fmt.resolution()
        area = size.width() * size.height()
        within_cap = area <= MAX_FRAME_AREA
        fps = fmt.maxFrameRate()
        cheap = not _is_compressed(fmt.pixelFormat()) and fps >= MIN_UNCOMPRESSED_FPS
        return (
            0 if within_cap else 1,
            -area if within_cap else area,
            0 if cheap else 1,
            -min(fps, 60.0),
        )

    return min(formats, key=key)


def qimage_to_bgra(image: QImage) -> NDArray[np.uint8]:
    """Copy a QImage into a (H, W, 4) BGRA numpy array, the format every capture source returns."""
    if image.format() != QImage.Format.Format_ARGB32:
        image = image.convertToFormat(QImage.Format.Format_ARGB32)
    height, width, stride = image.height(), image.width(), image.bytesPerLine()
    # ARGB32 is one 0xAARRGGBB uint32 per pixel, stored little-endian: B, G, R, A in memory
    rows = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(height, stride)
    return rows[:, : width * 4].reshape(height, width, 4).copy()


class VideoDeviceCapture(QObject):
    """Capture source reading from a video device, conforming to the Capture protocol.

    Qt keeps the device streaming at its own frame rate; get_frame() converts whichever frame
    is current when the GUI's processing timer fires.
    """

    def __init__(self, device: QCameraDevice, parent: QObject | None = None):
        super().__init__(parent)
        self._device = device
        self._invalid = False
        self._error: str | None = None
        self._frames = 0

        self._camera = QCamera(device, self)
        self._sink = QVideoSink(self)
        self._session = QMediaCaptureSession(self)
        self._session.setCamera(self._camera)
        self._session.setVideoSink(self._sink)
        self._camera.errorOccurred.connect(self._on_camera_error)
        self._sink.videoFrameChanged.connect(self._on_frame)

        # Unplugging the card doesn't always surface as a camera error
        self._devices = QMediaDevices(self)
        self._devices.videoInputsChanged.connect(self._on_devices_changed)

    @property
    def name(self) -> str:
        return self._device.description()

    @property
    def error(self) -> str | None:
        """Last camera error message, if any."""
        return self._error

    def start(self) -> None:
        """Open the device in the chosen mode and start streaming."""
        fmt = choose_format(list(self._device.videoFormats()))
        if fmt is not None:
            self._camera.setCameraFormat(fmt)
            size = fmt.resolution()
            logger.info(
                "starting video device capture",
                device=self.name,
                width=size.width(),
                height=size.height(),
                fps=round(fmt.maxFrameRate(), 1),
                pixel_format=fmt.pixelFormat().name,
            )
        else:
            logger.info("starting video device capture with default format", device=self.name)
        self._camera.start()

    def get_frame(self) -> NDArray[np.uint8] | None:
        frame = self._sink.videoFrame()
        if not frame.isValid():
            return None
        image = frame.toImage()
        if image.isNull():
            return None
        return qimage_to_bgra(image)

    @property
    def bounds(self) -> dict | None:
        """No window on screen, so no bounds (banner mode only, like Wayland)."""
        return None

    @property
    def window_invalid(self) -> bool:
        return self._invalid

    def get_content_offset(self) -> tuple[int, int]:
        return (0, 0)

    def stop(self) -> None:
        logger.info("stopping video device capture", device=self.name, frames=self._frames)
        self._camera.stop()
        self._session.setCamera(None)
        self._session.setVideoSink(None)
        # The GUI drops its reference; free the Qt objects once the event loop is idle
        self.deleteLater()

    @Slot(QVideoFrame)
    def _on_frame(self, frame: QVideoFrame) -> None:
        self._frames += 1

    @Slot(QCamera.Error, str)
    def _on_camera_error(self, error: QCamera.Error, message: str) -> None:
        if error == QCamera.Error.NoError:
            return
        logger.error("video device error", device=self.name, error=message)
        self._error = message or "camera error"
        self._invalid = True

    @Slot()
    def _on_devices_changed(self) -> None:
        if not any(device.id() == self._device.id() for device in list_video_devices()):
            logger.info("video device disconnected", device=self.name)
            self._error = "device disconnected"
            self._invalid = True
