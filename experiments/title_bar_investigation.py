#!/usr/bin/env python3
"""Investigate title bar height for window capture on macOS."""

import os
import sys

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from Quartz import CoreGraphics as CG
from PIL import Image
import objc
from AppKit import NSWorkspace, NSScreen


def get_window_list():
    """Get all windows with their properties."""
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


def capture_window_raw(window_id: int) -> Image.Image:
    """Capture window WITHOUT any cropping."""
    cg_image = CG.CGWindowListCreateImage(
        CG.CGRectNull,
        CG.kCGWindowListOptionIncludingWindow,
        window_id,
        CG.kCGWindowImageBoundsIgnoreFraming
    )

    if cg_image is None:
        return None

    width = CG.CGImageGetWidth(cg_image)
    height = CG.CGImageGetHeight(cg_image)
    bytes_per_row = CG.CGImageGetBytesPerRow(cg_image)

    data_provider = CG.CGImageGetDataProvider(cg_image)
    data = CG.CGDataProviderCopyData(data_provider)

    if bytes_per_row == width * 4:
        image = Image.frombytes("RGBA", (width, height), bytes(data), "raw", "BGRA")
    else:
        import numpy as np
        arr = np.frombuffer(data, dtype=np.uint8).reshape((height, bytes_per_row))
        arr = arr[:, :width * 4].reshape((height, width, 4))
        image = Image.fromarray(arr[:, :, [2, 1, 0, 3]], "RGBA")

    return image.convert("RGB")


def get_main_display_scale():
    """Get the scale factor of the main display."""
    screen = NSScreen.mainScreen()
    return screen.backingScaleFactor()


def main():
    print("=== Title Bar Investigation ===\n")

    # Get display scale
    scale = get_main_display_scale()
    print(f"Display scale factor: {scale}x\n")

    # List windows
    windows = get_window_list()
    print("Available windows:")
    for i, w in enumerate(windows):
        bounds = w["bounds"]
        print(f"  {i}: {w['title'][:50]} ({w['owner']}) - {int(bounds['Width'])}x{int(bounds['Height'])}")

    # Check for command line argument
    if len(sys.argv) > 1:
        choice = sys.argv[1]
    else:
        print("\nUsage: python title_bar_investigation.py <window_number>")
        return

    try:
        idx = int(choice)
        window = windows[idx]
    except (ValueError, IndexError):
        print("Invalid choice")
        return

    print(f"\nCapturing: {window['title']}")
    print(f"Window bounds from API: {window['bounds']}")

    # Capture raw (no cropping)
    image = capture_window_raw(window["id"])
    if image is None:
        print("Capture failed!")
        return

    print(f"Captured image size: {image.width}x{image.height}")

    # Calculate the difference
    api_width = int(window["bounds"]["Width"])
    api_height = int(window["bounds"]["Height"])

    print(f"\nAPI reports: {api_width}x{api_height}")
    print(f"Captured:    {image.width}x{image.height}")

    if scale > 1:
        print(f"\nWith {scale}x scaling:")
        print(f"  API in pixels: {int(api_width * scale)}x{int(api_height * scale)}")

    # Save the raw capture
    output_path = "/tmp/window_capture_raw.png"
    image.save(output_path)
    print(f"\nSaved raw capture to: {output_path}")

    # Also save just the top portion to inspect title bar
    top_portion = image.crop((0, 0, image.width, min(100, image.height)))
    top_path = "/tmp/window_capture_top.png"
    top_portion.save(top_path)
    print(f"Saved top 100px to: {top_path}")

    print("\nOpen the images to inspect the title bar area.")
    print("The title bar height should be visible in the raw capture.")

    # Try to detect title bar by looking for uniform color at top
    print("\n=== Attempting automatic title bar detection ===")

    # Sample pixels across the top rows
    from collections import Counter

    for y in range(min(80, image.height)):
        # Sample pixels across this row
        row_colors = []
        for x in range(0, image.width, 10):
            row_colors.append(image.getpixel((x, y)))

        # Check if row is mostly uniform (likely title bar)
        unique_colors = len(set(row_colors))
        if unique_colors > 5:  # Content has more variation
            print(f"Content likely starts at row {y} (found {unique_colors} unique colors)")
            print(f"Suggested title bar height: {y} pixels")
            if scale > 1:
                print(f"In points: {y / scale}")
            break
    else:
        print("Could not auto-detect title bar boundary")


if __name__ == "__main__":
    main()
