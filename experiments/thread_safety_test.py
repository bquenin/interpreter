#!/usr/bin/env python3
"""Test if NSScreen/NSWindow calls are slow from background thread."""

import os
import sys
import time
import threading

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from AppKit import NSWindow, NSScreen, NSTitledWindowMask, NSClosableWindowMask, NSMiniaturizableWindowMask
from Quartz import CoreGraphics as CG


def get_title_bar_height_slow():
    """The current implementation that might be slow."""
    scale = NSScreen.mainScreen().backingScaleFactor()
    content_rect = ((0, 0), (100, 100))
    style_mask = NSTitledWindowMask | NSClosableWindowMask | NSMiniaturizableWindowMask
    frame_rect = NSWindow.frameRectForContentRect_styleMask_(content_rect, style_mask)
    title_bar_points = frame_rect[1][1] - content_rect[1][1]
    return int(title_bar_points * scale)


def test_from_main_thread():
    """Test timing from main thread."""
    print("=== Main Thread Test ===")
    times = []
    for i in range(20):
        t0 = time.perf_counter()
        height = get_title_bar_height_slow()
        elapsed = (time.perf_counter() - t0) * 1000
        times.append(elapsed)
        if i < 5:
            print(f"  {i+1}: {elapsed:.2f}ms (height={height})")
    print(f"  Average: {sum(times)/len(times):.2f}ms")
    print(f"  Max: {max(times):.2f}ms")


def test_from_background_thread():
    """Test timing from background thread."""
    print("\n=== Background Thread Test ===")
    results = []

    def run():
        times = []
        for i in range(20):
            t0 = time.perf_counter()
            height = get_title_bar_height_slow()
            elapsed = (time.perf_counter() - t0) * 1000
            times.append(elapsed)
            if i < 5:
                print(f"  {i+1}: {elapsed:.2f}ms (height={height})")
        results.append(times)

    thread = threading.Thread(target=run)
    thread.start()
    thread.join()

    if results:
        times = results[0]
        print(f"  Average: {sum(times)/len(times):.2f}ms")
        print(f"  Max: {max(times):.2f}ms")


def test_is_fullscreen_timing(window_id: int):
    """Test fullscreen check timing."""
    print(f"\n=== Fullscreen Check Timing (window {window_id}) ===")

    def is_fullscreen(wid):
        # Get window bounds
        window_list = CG.CGWindowListCopyWindowInfo(
            CG.kCGWindowListOptionIncludingWindow,
            wid
        )
        bounds = None
        for window in window_list:
            if window.get(CG.kCGWindowNumber) == wid:
                b = window.get(CG.kCGWindowBounds, {})
                bounds = {
                    "x": int(b.get("X", 0)),
                    "y": int(b.get("Y", 0)),
                    "width": int(b.get("Width", 0)),
                    "height": int(b.get("Height", 0)),
                }
                break

        if bounds is None:
            return False

        # Get displays
        max_displays = 16
        (err, display_ids, display_count) = CG.CGGetActiveDisplayList(max_displays, None, None)
        if err != 0 or display_count == 0:
            return False

        window_center_x = bounds["x"] + bounds["width"] // 2
        window_center_y = bounds["y"] + bounds["height"] // 2

        for display_id in display_ids[:display_count]:
            display_bounds = CG.CGDisplayBounds(display_id)
            dx = int(display_bounds.origin.x)
            dy = int(display_bounds.origin.y)
            dw = int(display_bounds.size.width)
            dh = int(display_bounds.size.height)

            if dx <= window_center_x < dx + dw and dy <= window_center_y < dy + dh:
                return (
                    bounds["x"] == dx and
                    bounds["y"] <= dy + 50 and
                    bounds["width"] == dw and
                    bounds["height"] >= dh - 50
                )

        return False

    # Main thread
    print("From main thread:")
    times = []
    for i in range(20):
        t0 = time.perf_counter()
        result = is_fullscreen(window_id)
        elapsed = (time.perf_counter() - t0) * 1000
        times.append(elapsed)
        if i < 5:
            print(f"  {i+1}: {elapsed:.2f}ms (fullscreen={result})")
    print(f"  Average: {sum(times)/len(times):.2f}ms")

    # Background thread
    print("\nFrom background thread:")
    results = []

    def run():
        times = []
        for i in range(20):
            t0 = time.perf_counter()
            result = is_fullscreen(window_id)
            elapsed = (time.perf_counter() - t0) * 1000
            times.append(elapsed)
            if i < 5:
                print(f"  {i+1}: {elapsed:.2f}ms (fullscreen={result})")
        results.append(times)

    thread = threading.Thread(target=run)
    thread.start()
    thread.join()

    if results:
        times = results[0]
        print(f"  Average: {sum(times)/len(times):.2f}ms")


def main():
    from interpreter.capture.macos import get_window_list

    print("=== Thread Safety Test ===\n")

    windows = get_window_list()
    if len(sys.argv) < 2:
        print("Available windows:")
        for i, w in enumerate(windows):
            print(f"  {i}: {w['title'][:50]}")
        print("\nUsage: python thread_safety_test.py <window_number>")
        return

    try:
        idx = int(sys.argv[1])
        window = windows[idx]
    except (ValueError, IndexError):
        print("Invalid choice")
        return

    test_from_main_thread()
    test_from_background_thread()
    test_is_fullscreen_timing(window["id"])


if __name__ == "__main__":
    main()
