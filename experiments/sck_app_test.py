#!/usr/bin/env python3
"""ScreenCaptureKit test with proper NSApplication context."""

import os
import sys
import time
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Initialize NSApplication FIRST before any CG calls
from AppKit import NSApplication, NSApp
app = NSApplication.sharedApplication()

import objc
from Foundation import NSRunLoop, NSDate, NSObject
import Quartz

# Now load ScreenCaptureKit
objc.loadBundle(
    'ScreenCaptureKit',
    globals(),
    bundle_path='/System/Library/Frameworks/ScreenCaptureKit.framework'
)

# Register metadata
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

objc.registerMetaDataForSelector(
    b'SCScreenshotManager',
    b'captureImageWithFilter:configuration:completionHandler:',
    {
        'arguments': {
            4: {
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

print("ScreenCaptureKit loaded with NSApplication context!")


def get_windows():
    """Get shareable windows."""
    result = {"content": None}
    done = threading.Event()

    def handler(content, error):
        result["content"] = content
        done.set()

    SCShareableContent.getShareableContentWithCompletionHandler_(handler)

    timeout = time.time() + 5.0
    while not done.is_set() and time.time() < timeout:
        NSRunLoop.currentRunLoop().runUntilDate_(
            NSDate.dateWithTimeIntervalSinceNow_(0.1)
        )

    if result["content"] is None:
        return []

    windows = []
    for w in result["content"].windows():
        title = w.title()
        if not title:
            continue
        app_obj = w.owningApplication()
        owner = app_obj.applicationName() if app_obj else ""
        # Skip system stuff
        if "Control Center" in owner or not owner:
            continue
        windows.append({
            "title": title,
            "owner": owner,
            "window": w,
        })

    return sorted(windows, key=lambda x: x["title"].lower())


def capture_once(window):
    """Single screenshot capture."""
    content_filter = SCContentFilter.alloc().initWithDesktopIndependentWindow_(window)

    config = SCStreamConfiguration.alloc().init()
    config.setWidth_(3840)
    config.setHeight_(2160)
    config.setShowsCursor_(False)

    result = {"image": None, "error": None}
    done = threading.Event()

    def handler(image, error):
        result["image"] = image
        result["error"] = error
        done.set()

    SCScreenshotManager.captureImageWithFilter_configuration_completionHandler_(
        content_filter, config, handler
    )

    timeout = time.time() + 2.0
    while not done.is_set() and time.time() < timeout:
        NSRunLoop.currentRunLoop().runUntilDate_(
            NSDate.dateWithTimeIntervalSinceNow_(0.01)
        )

    return result["image"], result["error"]


def main():
    windows = get_windows()
    if not windows:
        print("No windows found")
        return

    print(f"\nFound {len(windows)} windows:")
    for i, w in enumerate(windows):
        print(f"  {i}: {w['title'][:40]} ({w['owner']})")

    if len(sys.argv) < 2:
        print("\nUsage: python sck_app_test.py <number>")
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

    while time.time() - start < 20:
        t0 = time.perf_counter()
        image, error = capture_once(window)
        capture_time = (time.perf_counter() - t0) * 1000

        if image:
            frame_count += 1

        now = time.time()
        if now - last_report >= 1.0:
            elapsed = now - start
            fps = frame_count / elapsed if elapsed > 0 else 0
            status = "OK" if image else f"ERR"
            print(f"FPS: {fps:.1f} | Capture: {capture_time:.0f}ms | {status}")
            last_report = now

    total_time = time.time() - start
    print(f"\nTotal frames: {frame_count}")
    print(f"Average FPS: {frame_count / total_time:.1f}")


if __name__ == "__main__":
    main()
