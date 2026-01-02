#!/usr/bin/env python3
"""Investigate fullscreen capture performance."""

import os
import sys
import time

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from Quartz import CoreGraphics as CG
from AppKit import NSWindow, NSScreen, NSTitledWindowMask, NSClosableWindowMask, NSMiniaturizableWindowMask
from PIL import Image


def get_window_list():
    """Get all windows."""
    windows = []
    window_list = CG.CGWindowListCopyWindowInfo(
        CG.kCGWindowListOptionAll | CG.kCGWindowListExcludeDesktopElements,
        CG.kCGNullWindowID
    )

    for window in window_list:
        window_id = window.get(CG.kCGWindowNumber)
        title = window.get(CG.kCGWindowName, "")
        owner = window.get(CG.kCGWindowOwnerName, "")
        bounds = window.get(CG.kCGWindowBounds, {})
        layer = window.get(CG.kCGWindowLayer, -1)

        if layer != 0 or not title:
            continue

        windows.append({
            "id": window_id,
            "title": title,
            "owner": owner,
            "bounds": bounds,
        })

    return sorted(windows, key=lambda w: w["title"].lower())


def get_window_bounds(window_id: int):
    """Get window bounds."""
    window_list = CG.CGWindowListCopyWindowInfo(
        CG.kCGWindowListOptionIncludingWindow,
        window_id
    )
    for window in window_list:
        if window.get(CG.kCGWindowNumber) == window_id:
            bounds = window.get(CG.kCGWindowBounds, {})
            return {
                "x": int(bounds.get("X", 0)),
                "y": int(bounds.get("Y", 0)),
                "width": int(bounds.get("Width", 0)),
                "height": int(bounds.get("Height", 0)),
            }
    return None


def is_fullscreen(window_id: int) -> bool:
    """Check if window is fullscreen."""
    bounds = get_window_bounds(window_id)
    if bounds is None:
        return False

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
            is_fs = (
                bounds["x"] == dx and
                bounds["y"] <= dy + 50 and
                bounds["width"] == dw and
                bounds["height"] >= dh - 50
            )
            return is_fs

    return False


def get_title_bar_height():
    """Get title bar height in pixels."""
    scale = NSScreen.mainScreen().backingScaleFactor()
    content_rect = ((0, 0), (100, 100))
    style_mask = NSTitledWindowMask | NSClosableWindowMask | NSMiniaturizableWindowMask
    frame_rect = NSWindow.frameRectForContentRect_styleMask_(content_rect, style_mask)
    title_bar_points = frame_rect[1][1] - content_rect[1][1]
    return int(title_bar_points * scale)


def capture_window_timed(window_id: int, skip_fullscreen_check: bool = False, skip_title_bar_crop: bool = False):
    """Capture window with timing for each step."""
    timings = {}

    # Step 1: Fullscreen check
    t0 = time.perf_counter()
    if skip_fullscreen_check:
        is_fs = False
    else:
        is_fs = is_fullscreen(window_id)
    timings["fullscreen_check"] = (time.perf_counter() - t0) * 1000

    # Step 2: Title bar height
    t0 = time.perf_counter()
    if skip_title_bar_crop or is_fs:
        title_bar_height = 0
    else:
        title_bar_height = get_title_bar_height()
    timings["title_bar_calc"] = (time.perf_counter() - t0) * 1000

    # Step 3: CGWindowListCreateImage
    t0 = time.perf_counter()
    cg_image = CG.CGWindowListCreateImage(
        CG.CGRectNull,
        CG.kCGWindowListOptionIncludingWindow,
        window_id,
        CG.kCGWindowImageBoundsIgnoreFraming
    )
    timings["cg_capture"] = (time.perf_counter() - t0) * 1000

    if cg_image is None:
        return None, timings

    # Step 4: Get image properties
    t0 = time.perf_counter()
    width = CG.CGImageGetWidth(cg_image)
    height = CG.CGImageGetHeight(cg_image)
    bytes_per_row = CG.CGImageGetBytesPerRow(cg_image)
    timings["get_props"] = (time.perf_counter() - t0) * 1000

    if width == 0 or height == 0:
        return None, timings

    # Step 5: Copy data
    t0 = time.perf_counter()
    data_provider = CG.CGImageGetDataProvider(cg_image)
    data = CG.CGDataProviderCopyData(data_provider)
    timings["copy_data"] = (time.perf_counter() - t0) * 1000

    # Step 6: Create PIL image
    t0 = time.perf_counter()
    if bytes_per_row == width * 4:
        image = Image.frombytes("RGBA", (width, height), bytes(data), "raw", "BGRA")
    else:
        import numpy as np
        arr = np.frombuffer(data, dtype=np.uint8).reshape((height, bytes_per_row))
        arr = arr[:, :width * 4].reshape((height, width, 4))
        image = Image.fromarray(arr[:, :, [2, 1, 0, 3]], "RGBA")
    timings["pil_create"] = (time.perf_counter() - t0) * 1000

    # Step 7: Convert to RGB
    t0 = time.perf_counter()
    image = image.convert("RGB")
    timings["rgb_convert"] = (time.perf_counter() - t0) * 1000

    # Step 8: Crop title bar
    t0 = time.perf_counter()
    if title_bar_height > 0 and height > title_bar_height:
        image = image.crop((0, title_bar_height, width, height))
    timings["crop"] = (time.perf_counter() - t0) * 1000

    timings["total"] = sum(timings.values())
    timings["image_size"] = f"{image.width}x{image.height}"
    timings["is_fullscreen"] = is_fs

    return image, timings


def main():
    print("=== Fullscreen Performance Investigation ===\n")

    windows = get_window_list()
    print("Available windows:")
    for i, w in enumerate(windows):
        bounds = w["bounds"]
        print(f"  {i}: {w['title'][:50]} ({w['owner']}) - {int(bounds['Width'])}x{int(bounds['Height'])}")

    if len(sys.argv) < 2:
        print("\nUsage: python fullscreen_perf.py <window_number>")
        return

    try:
        idx = int(sys.argv[1])
        window = windows[idx]
    except (ValueError, IndexError):
        print("Invalid choice")
        return

    window_id = window["id"]
    print(f"\nCapturing: {window['title']}")
    print(f"Window ID: {window_id}")

    # Check fullscreen status
    is_fs = is_fullscreen(window_id)
    print(f"Fullscreen: {is_fs}")

    # Warm up
    print("\nWarming up...")
    for _ in range(3):
        capture_window_timed(window_id)

    # Benchmark: normal capture
    print("\n=== Normal Capture (10 iterations) ===")
    for i in range(10):
        image, timings = capture_window_timed(window_id)
        if image:
            print(f"  {i+1}: total={timings['total']:.1f}ms | "
                  f"fs_check={timings['fullscreen_check']:.1f}ms | "
                  f"cg_capture={timings['cg_capture']:.1f}ms | "
                  f"copy_data={timings['copy_data']:.1f}ms | "
                  f"pil={timings['pil_create']:.1f}ms | "
                  f"size={timings['image_size']}")
        else:
            print(f"  {i+1}: FAILED")
        time.sleep(0.1)

    # Benchmark: skip fullscreen check
    print("\n=== Skip Fullscreen Check (10 iterations) ===")
    for i in range(10):
        image, timings = capture_window_timed(window_id, skip_fullscreen_check=True)
        if image:
            print(f"  {i+1}: total={timings['total']:.1f}ms | "
                  f"cg_capture={timings['cg_capture']:.1f}ms | "
                  f"copy_data={timings['copy_data']:.1f}ms | "
                  f"size={timings['image_size']}")
        else:
            print(f"  {i+1}: FAILED")
        time.sleep(0.1)

    # Continuous capture to measure FPS
    print("\n=== Continuous Capture (5 seconds) ===")
    start = time.perf_counter()
    frame_count = 0
    while time.perf_counter() - start < 5.0:
        image, _ = capture_window_timed(window_id)
        if image:
            frame_count += 1

    elapsed = time.perf_counter() - start
    fps = frame_count / elapsed
    print(f"Frames: {frame_count}, Time: {elapsed:.2f}s, FPS: {fps:.1f}")


if __name__ == "__main__":
    main()
