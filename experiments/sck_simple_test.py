#!/usr/bin/env python3
"""Simple ScreenCaptureKit test using screenshot API."""

import os
import sys
import time
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

try:
    import objc
    from Foundation import NSRunLoop, NSDate
    import Quartz

    # Load ScreenCaptureKit
    objc.loadBundle(
        'ScreenCaptureKit',
        globals(),
        bundle_path='/System/Library/Frameworks/ScreenCaptureKit.framework'
    )

    # Register metadata for completion handlers
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

    # For captureImageWithFilter:configuration:completionHandler:
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
                            1: {'type': b'@'},  # CGImageRef
                            2: {'type': b'@'},  # NSError
                        }
                    }
                }
            }
        }
    )

    HAS_SCK = True
    print("ScreenCaptureKit loaded!")
except Exception as e:
    print(f"Failed to load ScreenCaptureKit: {e}")
    HAS_SCK = False


def get_windows():
    """Get shareable windows."""
    if not HAS_SCK:
        return []

    result = {"content": None, "error": None}
    done = threading.Event()

    def handler(content, error):
        result["content"] = content
        result["error"] = error
        done.set()

    SCShareableContent.getShareableContentWithCompletionHandler_(handler)

    # Run the run loop to process the callback
    timeout = time.time() + 5.0
    while not done.is_set() and time.time() < timeout:
        NSRunLoop.currentRunLoop().runUntilDate_(
            NSDate.dateWithTimeIntervalSinceNow_(0.1)
        )

    if result["error"] or result["content"] is None:
        return []

    windows = []
    for w in result["content"].windows():
        title = w.title()
        if not title:
            continue
        app = w.owningApplication()
        windows.append({
            "title": title,
            "owner": app.applicationName() if app else "",
            "window": w,
        })

    return sorted(windows, key=lambda x: x["title"].lower())


def capture_once(window):
    """Capture a single screenshot using SCScreenshotManager."""
    # Create filter
    content_filter = SCContentFilter.alloc().initWithDesktopIndependentWindow_(window)

    # Create config
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

    # Use SCScreenshotManager for single capture
    SCScreenshotManager.captureImageWithFilter_configuration_completionHandler_(
        content_filter, config, handler
    )

    # Wait for completion
    timeout = time.time() + 5.0
    while not done.is_set() and time.time() < timeout:
        NSRunLoop.currentRunLoop().runUntilDate_(
            NSDate.dateWithTimeIntervalSinceNow_(0.05)
        )

    return result["image"], result["error"]


def main():
    if not HAS_SCK:
        return

    windows = get_windows()
    if not windows:
        print("No windows found")
        return

    # Filter to show only app windows
    app_windows = [w for w in windows if w["owner"] and "Control Center" not in w["owner"]]

    print(f"\nFound {len(app_windows)} app windows:")
    for i, w in enumerate(app_windows):
        print(f"  {i}: {w['title'][:40]} ({w['owner']})")

    if len(sys.argv) < 2:
        print("\nUsage: python sck_simple_test.py <number>")
        return

    idx = int(sys.argv[1])
    window_info = app_windows[idx]
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
            fps = frame_count / (now - start)
            status = "OK" if image else f"ERR: {error}"
            print(f"FPS: {fps:.1f} | Capture: {capture_time:.0f}ms | {status}")
            last_report = now

    print(f"\nTotal frames: {frame_count}")
    print(f"Average FPS: {frame_count / 20:.1f}")


if __name__ == "__main__":
    main()
