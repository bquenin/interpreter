#!/usr/bin/env python3
"""Test ScreenCaptureKit streaming API like OBS does."""

import sys
import time
import threading
import ctypes

# Initialize NSApplication first
from AppKit import NSApplication
NSApplication.sharedApplication()

import objc
from Foundation import NSObject, NSRunLoop, NSDate
import ScreenCaptureKit
import Quartz
import CoreMedia
from PIL import Image
import numpy as np


# Define the delegate class for receiving stream output
class StreamDelegate(NSObject):
    """Delegate to receive SCStream output frames."""

    def init(self):
        self = objc.super(StreamDelegate, self).init()
        if self is None:
            return None
        self.frame_count = 0
        self.latest_frame = None
        self.lock = threading.Lock()
        return self

    # SCStreamOutput protocol method
    def stream_didOutputSampleBuffer_ofType_(self, stream, sampleBuffer, outputType):
        """Called when a new frame is available."""
        # outputType 0 = SCStreamOutputTypeScreen
        if outputType != 0:
            return

        try:
            # Get the pixel buffer from sample buffer
            imageBuffer = Quartz.CMSampleBufferGetImageBuffer(sampleBuffer)
            if imageBuffer is None:
                return

            # Lock buffer
            Quartz.CVPixelBufferLockBaseAddress(imageBuffer, 0)

            try:
                width = Quartz.CVPixelBufferGetWidth(imageBuffer)
                height = Quartz.CVPixelBufferGetHeight(imageBuffer)
                bytes_per_row = Quartz.CVPixelBufferGetBytesPerRow(imageBuffer)
                base_address = Quartz.CVPixelBufferGetBaseAddress(imageBuffer)

                if base_address and width > 0 and height > 0:
                    # Create numpy array
                    buffer_ptr = ctypes.cast(base_address, ctypes.POINTER(ctypes.c_uint8))
                    arr = np.ctypeslib.as_array(buffer_ptr, shape=(height, bytes_per_row))
                    bgra = arr[:, :width * 4].reshape((height, width, 4)).copy()
                    rgb = bgra[:, :, [2, 1, 0]]

                    with self.lock:
                        self.latest_frame = Image.fromarray(rgb, 'RGB')
                        self.frame_count += 1

            finally:
                Quartz.CVPixelBufferUnlockBaseAddress(imageBuffer, 0)

        except Exception as e:
            print(f"Frame error: {e}")

    def stream_didStopWithError_(self, stream, error):
        """Called when stream stops."""
        if error:
            print(f"Stream stopped with error: {error}")


def get_windows():
    """Get shareable windows."""
    result = {"content": None}
    done = threading.Event()

    def handler(content, error):
        result["content"] = content
        if error:
            print(f"Error: {error}")
        done.set()

    ScreenCaptureKit.SCShareableContent.getShareableContentWithCompletionHandler_(handler)

    timeout = time.time() + 5.0
    while not done.is_set() and time.time() < timeout:
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.1))

    if result["content"] is None:
        return []

    windows = []
    for w in result["content"].windows():
        title = w.title()
        if not title:
            continue
        app = w.owningApplication()
        owner = app.applicationName() if app else ""
        if not owner or "Control Center" in owner:
            continue
        windows.append({"title": title, "owner": owner, "window": w})

    return sorted(windows, key=lambda x: x["title"].lower())


def run_stream_capture(window):
    """Run streaming capture like OBS does."""
    print(f"Setting up stream capture...")

    # Create content filter
    content_filter = ScreenCaptureKit.SCContentFilter.alloc().initWithDesktopIndependentWindow_(window)

    # Create stream configuration (like OBS)
    config = ScreenCaptureKit.SCStreamConfiguration.alloc().init()
    config.setWidth_(3840)
    config.setHeight_(2160)
    config.setShowsCursor_(False)
    config.setQueueDepth_(8)  # OBS uses 8
    config.setPixelFormat_(Quartz.kCVPixelFormatType_32BGRA)

    # Set frame interval for 60 FPS (CMTime: 1/60 second)
    frame_interval = CoreMedia.CMTimeMake(1, 60)
    config.setMinimumFrameInterval_(frame_interval)

    # Create delegate
    delegate = StreamDelegate.alloc().init()

    # Create stream (like OBS: initWithFilter:configuration:delegate:)
    stream = ScreenCaptureKit.SCStream.alloc().initWithFilter_configuration_delegate_(
        content_filter, config, delegate
    )

    # Add stream output with nil queue (like OBS)
    error = None
    success = stream.addStreamOutput_type_sampleHandlerQueue_error_(
        delegate,
        0,  # SCStreamOutputTypeScreen
        None,  # nil - use default queue like OBS
        None
    )

    if not success:
        print("Failed to add stream output")
        return

    # Start capture
    print("Starting stream...")
    start_done = threading.Event()
    start_error = {"error": None}

    def start_handler(error):
        start_error["error"] = error
        start_done.set()

    stream.startCaptureWithCompletionHandler_(start_handler)

    timeout = time.time() + 5.0
    while not start_done.is_set() and time.time() < timeout:
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.1))

    if start_error["error"]:
        print(f"Start error: {start_error['error']}")
        return

    print("Stream started!")
    print("\n" + "=" * 50)
    print("Switch to fullscreen game to test cross-Space FPS")
    print("=" * 50 + "\n")

    # Monitor for 30 seconds
    start_time = time.time()
    last_report = start_time
    last_count = 0

    try:
        while time.time() - start_time < 30:
            # Process run loop
            NSRunLoop.currentRunLoop().runUntilDate_(
                NSDate.dateWithTimeIntervalSinceNow_(0.1)
            )

            now = time.time()
            if now - last_report >= 1.0:
                with delegate.lock:
                    current_count = delegate.frame_count
                    frame = delegate.latest_frame

                fps = current_count - last_count  # Frames in last second
                total_fps = current_count / (now - start_time)
                size = f"{frame.width}x{frame.height}" if frame else "no frame"
                print(f"FPS: {fps:3d} | Avg: {total_fps:.1f} | Frames: {current_count:4d} | Size: {size}")

                last_count = current_count
                last_report = now

    except KeyboardInterrupt:
        print("\nInterrupted")

    # Stop capture
    print("\nStopping stream...")
    stop_done = threading.Event()

    def stop_handler(error):
        stop_done.set()

    stream.stopCaptureWithCompletionHandler_(stop_handler)

    timeout = time.time() + 5.0
    while not stop_done.is_set() and time.time() < timeout:
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.1))

    total_time = time.time() - start_time
    print(f"\nTotal frames: {delegate.frame_count}")
    print(f"Average FPS: {delegate.frame_count / total_time:.1f}")


def main():
    print("=== ScreenCaptureKit Streaming Test (OBS-style) ===\n")

    windows = get_windows()
    if not windows:
        print("No windows found")
        return

    print(f"Found {len(windows)} windows:")
    for i, w in enumerate(windows):
        print(f"  {i}: {w['title'][:40]} ({w['owner']})")

    if len(sys.argv) < 2:
        print("\nUsage: python sck_stream_test.py <number>")
        return

    idx = int(sys.argv[1])
    window_info = windows[idx]

    print(f"\nCapturing: {window_info['title']}")
    run_stream_capture(window_info["window"])


if __name__ == "__main__":
    main()
