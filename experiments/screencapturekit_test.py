#!/usr/bin/env python3
"""Test ScreenCaptureKit for window capture - Apple's modern API (macOS 12.3+)."""

import os
import sys
import time
import threading
import ctypes

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Try to load ScreenCaptureKit framework
try:
    import objc
    from Foundation import NSObject, NSRunLoop, NSDate, NSError
    from Quartz import CoreGraphics as CG
    import Quartz

    # Load ScreenCaptureKit framework
    objc.loadBundle(
        'ScreenCaptureKit',
        globals(),
        bundle_path='/System/Library/Frameworks/ScreenCaptureKit.framework'
    )

    # Register block signatures manually
    # SCShareableContent completion: void (^)(SCShareableContent *, NSError *)
    objc.registerMetaDataForSelector(
        b'SCShareableContent',
        b'getShareableContentWithCompletionHandler:',
        {
            'arguments': {
                2: {
                    'callable': {
                        'retval': {'type': b'v'},
                        'arguments': {
                            0: {'type': b'^v'},
                            1: {'type': b'@'},
                            2: {'type': b'@'},
                        }
                    }
                }
            }
        }
    )

    # SCStream start completion: void (^)(NSError *)
    objc.registerMetaDataForSelector(
        b'SCStream',
        b'startCaptureWithCompletionHandler:',
        {
            'arguments': {
                2: {
                    'callable': {
                        'retval': {'type': b'v'},
                        'arguments': {
                            0: {'type': b'^v'},
                            1: {'type': b'@'},
                        }
                    }
                }
            }
        }
    )

    # SCStream stop completion: void (^)(NSError *)
    objc.registerMetaDataForSelector(
        b'SCStream',
        b'stopCaptureWithCompletionHandler:',
        {
            'arguments': {
                2: {
                    'callable': {
                        'retval': {'type': b'v'},
                        'arguments': {
                            0: {'type': b'^v'},
                            1: {'type': b'@'},
                        }
                    }
                }
            }
        }
    )

    HAS_SCK = True
    print("ScreenCaptureKit loaded successfully!")
except Exception as e:
    print(f"ScreenCaptureKit not available: {e}")
    import traceback
    traceback.print_exc()
    HAS_SCK = False

from PIL import Image
import numpy as np


if HAS_SCK:
    class StreamDelegate(NSObject):
        """Delegate to receive stream output and errors."""

        def init(self):
            self = objc.super(StreamDelegate, self).init()
            if self is None:
                return None
            self.latest_frame = None
            self.frame_count = 0
            self.lock = threading.Lock()
            self.error = None
            return self

        def stream_didOutputSampleBuffer_ofType_(self, stream, sampleBuffer, outputType):
            """Called when a new frame is available."""
            try:
                # Get the image buffer from the sample buffer
                imageBuffer = Quartz.CMSampleBufferGetImageBuffer(sampleBuffer)
                if imageBuffer is None:
                    return

                # Lock the pixel buffer
                Quartz.CVPixelBufferLockBaseAddress(imageBuffer, 0)

                try:
                    width = Quartz.CVPixelBufferGetWidth(imageBuffer)
                    height = Quartz.CVPixelBufferGetHeight(imageBuffer)
                    bytes_per_row = Quartz.CVPixelBufferGetBytesPerRow(imageBuffer)
                    base_address = Quartz.CVPixelBufferGetBaseAddress(imageBuffer)

                    if base_address and width > 0 and height > 0:
                        # Convert to numpy array
                        buffer_ptr = ctypes.cast(base_address, ctypes.POINTER(ctypes.c_uint8))

                        # Create array from pointer
                        arr = np.ctypeslib.as_array(buffer_ptr, shape=(height, bytes_per_row))

                        # Extract BGRA data
                        bgra = arr[:, :width * 4].reshape((height, width, 4)).copy()

                        # Convert BGRA to RGB
                        rgb = bgra[:, :, [2, 1, 0]]

                        with self.lock:
                            self.latest_frame = Image.fromarray(rgb, 'RGB')
                            self.frame_count += 1

                except Exception as e:
                    print(f"Frame processing error: {e}")
                finally:
                    Quartz.CVPixelBufferUnlockBaseAddress(imageBuffer, 0)

            except Exception as e:
                print(f"Output error: {e}")

        def stream_didStopWithError_(self, stream, error):
            """Called when stream stops with an error."""
            self.error = error
            if error:
                print(f"Stream stopped with error: {error}")


def get_shareable_windows():
    """Get list of windows available for ScreenCaptureKit capture."""
    if not HAS_SCK:
        return []

    result = {"content": None, "error": None}
    done = threading.Event()

    def completion_handler(content, error):
        result["content"] = content
        result["error"] = error
        done.set()

    # Request shareable content
    SCShareableContent.getShareableContentWithCompletionHandler_(completion_handler)

    # Wait with timeout
    if not done.wait(timeout=10.0):
        print("Timeout getting shareable content")
        return []

    if result["error"]:
        print(f"Error: {result['error']}")
        return []

    content = result["content"]
    if content is None:
        print("No shareable content returned")
        return []

    windows = []
    for window in content.windows():
        title = window.title()
        if not title:
            continue

        app = window.owningApplication()
        app_name = app.applicationName() if app else "Unknown"

        windows.append({
            "id": window.windowID(),
            "title": title,
            "owner": app_name,
            "scwindow": window,
        })

    return sorted(windows, key=lambda w: w["title"].lower())


def run_capture_test(window_info):
    """Run a capture test on the selected window."""
    window = window_info["scwindow"]

    print(f"\nSetting up capture for: {window_info['title']}")

    # Create content filter for this window
    content_filter = SCContentFilter.alloc().initWithDesktopIndependentWindow_(window)

    # Create stream configuration
    config = SCStreamConfiguration.alloc().init()
    config.setWidth_(3840)  # Support high res
    config.setHeight_(2160)
    config.setShowsCursor_(False)
    config.setPixelFormat_(Quartz.kCVPixelFormatType_32BGRA)

    # Set frame rate (CMTime: value/timescale = seconds per frame)
    frame_interval = Quartz.CMTimeMake(1, 60)  # 60 FPS
    config.setMinimumFrameInterval_(frame_interval)

    # Create delegate
    delegate = StreamDelegate.alloc().init()

    # Create stream
    stream = SCStream.alloc().initWithFilter_configuration_delegate_(
        content_filter, config, delegate
    )

    # Create dispatch queue for output
    queue = Quartz.dispatch_queue_create(b"com.interpreter.capture", None)

    # Add stream output
    error_ptr = objc.nil
    success = stream.addStreamOutput_type_sampleHandlerQueue_error_(
        delegate,
        0,  # SCStreamOutputTypeScreen = 0
        queue,
        error_ptr
    )

    if not success:
        print("Failed to add stream output")
        return

    # Start capture
    print("Starting capture...")
    start_done = threading.Event()
    start_error = {"error": None}

    def start_handler(error):
        start_error["error"] = error
        start_done.set()

    stream.startCaptureWithCompletionHandler_(start_handler)

    if not start_done.wait(timeout=5.0):
        print("Timeout starting capture")
        return

    if start_error["error"]:
        print(f"Start error: {start_error['error']}")
        return

    print("Capture started!")
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

                fps = (current_count - last_count) / (now - last_report)
                size = f"{frame.width}x{frame.height}" if frame else "no frame"
                print(f"FPS: {fps:5.1f} | Total frames: {current_count:4d} | Size: {size}")

                last_count = current_count
                last_report = now

    except KeyboardInterrupt:
        print("\nInterrupted")

    # Stop capture
    print("\nStopping capture...")
    stop_done = threading.Event()

    def stop_handler(error):
        stop_done.set()

    stream.stopCaptureWithCompletionHandler_(stop_handler)
    stop_done.wait(timeout=5.0)

    print("Done!")


def main():
    if not HAS_SCK:
        print("\nScreenCaptureKit requires macOS 12.3+")
        print("Make sure Screen Recording permission is granted in System Preferences.")
        return

    print("\n=== ScreenCaptureKit Cross-Space Test ===\n")

    # Get available windows
    print("Getting shareable windows...")
    windows = get_shareable_windows()

    if not windows:
        print("\nNo windows found!")
        print("Make sure Screen Recording permission is granted.")
        return

    print(f"\nFound {len(windows)} windows:")
    for i, w in enumerate(windows):
        print(f"  {i}: {w['title'][:50]} ({w['owner']})")

    if len(sys.argv) < 2:
        print("\nUsage: python screencapturekit_test.py <window_number>")
        return

    try:
        idx = int(sys.argv[1])
        window_info = windows[idx]
    except (ValueError, IndexError):
        print("Invalid choice")
        return

    run_capture_test(window_info)


if __name__ == "__main__":
    main()
