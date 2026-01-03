#!/usr/bin/env python3
"""Test using official pyobjc-framework-ScreenCaptureKit."""

import sys
import time
import threading

# Initialize NSApplication first for proper GUI context
from AppKit import NSApplication
NSApplication.sharedApplication()

import ScreenCaptureKit
from Foundation import NSRunLoop, NSDate
import Quartz
from PIL import Image
import numpy as np
import ctypes


def get_windows():
    """Get list of shareable windows."""
    result = {"content": None, "error": None}
    done = threading.Event()

    def handler(content, error):
        result["content"] = content
        result["error"] = error
        done.set()

    ScreenCaptureKit.SCShareableContent.getShareableContentWithCompletionHandler_(handler)

    # Wait for async completion
    timeout = time.time() + 5.0
    while not done.is_set() and time.time() < timeout:
        NSRunLoop.currentRunLoop().runUntilDate_(
            NSDate.dateWithTimeIntervalSinceNow_(0.1)
        )

    if result["content"] is None:
        print(f"Error getting content: {result['error']}")
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
        windows.append({
            "title": title,
            "owner": owner,
            "window": w,
        })

    return sorted(windows, key=lambda x: x["title"].lower())


def capture_screenshot(window):
    """Capture a single screenshot of the window."""
    # Create filter for this window
    content_filter = ScreenCaptureKit.SCContentFilter.alloc().initWithDesktopIndependentWindow_(window)

    # Create configuration
    config = ScreenCaptureKit.SCStreamConfiguration.alloc().init()
    config.setWidth_(3840)
    config.setHeight_(2160)
    config.setShowsCursor_(False)
    config.setPixelFormat_(Quartz.kCVPixelFormatType_32BGRA)

    result = {"image": None, "error": None}
    done = threading.Event()

    def handler(cg_image, error):
        result["image"] = cg_image
        result["error"] = error
        done.set()

    # Capture screenshot
    ScreenCaptureKit.SCScreenshotManager.captureImageWithFilter_configuration_completionHandler_(
        content_filter, config, handler
    )

    # Wait for completion
    timeout = time.time() + 2.0
    while not done.is_set() and time.time() < timeout:
        NSRunLoop.currentRunLoop().runUntilDate_(
            NSDate.dateWithTimeIntervalSinceNow_(0.01)
        )

    return result["image"], result["error"]


def cg_image_to_pil(cg_image):
    """Convert CGImage to PIL Image."""
    if cg_image is None:
        return None

    width = Quartz.CGImageGetWidth(cg_image)
    height = Quartz.CGImageGetHeight(cg_image)
    bytes_per_row = Quartz.CGImageGetBytesPerRow(cg_image)

    data_provider = Quartz.CGImageGetDataProvider(cg_image)
    data = Quartz.CGDataProviderCopyData(data_provider)

    if bytes_per_row == width * 4:
        image = Image.frombytes("RGBA", (width, height), bytes(data), "raw", "BGRA")
    else:
        arr = np.frombuffer(data, dtype=np.uint8).reshape((height, bytes_per_row))
        arr = arr[:, :width * 4].reshape((height, width, 4))
        image = Image.fromarray(arr[:, :, [2, 1, 0, 3]], "RGBA")

    return image.convert("RGB")


def main():
    print("=== ScreenCaptureKit Official Package Test ===\n")

    windows = get_windows()
    if not windows:
        print("No windows found. Check Screen Recording permission.")
        return

    print(f"Found {len(windows)} windows:")
    for i, w in enumerate(windows):
        print(f"  {i}: {w['title'][:40]} ({w['owner']})")

    if len(sys.argv) < 2:
        print("\nUsage: python sck_official_test.py <number>")
        return

    idx = int(sys.argv[1])
    window_info = windows[idx]
    window = window_info["window"]

    print(f"\nCapturing: {window_info['title']}")
    print("Switch to fullscreen game to test cross-Space capture...")
    print("Running for 20 seconds...\n")

    start = time.time()
    frame_count = 0
    last_report = start
    last_frame = None

    while time.time() - start < 20:
        t0 = time.perf_counter()
        cg_image, error = capture_screenshot(window)
        capture_time = (time.perf_counter() - t0) * 1000

        if cg_image:
            frame_count += 1
            last_frame = cg_image

        now = time.time()
        if now - last_report >= 1.0:
            elapsed = now - start
            fps = frame_count / elapsed if elapsed > 0 else 0
            if cg_image:
                w = Quartz.CGImageGetWidth(cg_image)
                h = Quartz.CGImageGetHeight(cg_image)
                size = f"{w}x{h}"
            else:
                size = "FAIL"
            print(f"FPS: {fps:.1f} | Capture: {capture_time:.0f}ms | Size: {size}")
            last_report = now

    total_time = time.time() - start
    print(f"\nTotal frames: {frame_count}")
    print(f"Average FPS: {frame_count / total_time:.1f}")

    # Save last frame
    if last_frame:
        pil_img = cg_image_to_pil(last_frame)
        if pil_img:
            pil_img.save("/tmp/sck_capture.png")
            print(f"Saved last frame to /tmp/sck_capture.png")


if __name__ == "__main__":
    main()
