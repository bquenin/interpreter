#!/usr/bin/env python3
"""Test the title bar cropping fix."""

import os
import sys

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from interpreter.capture.macos import get_window_list, capture_window, _get_title_bar_height_pixels
from AppKit import NSScreen


def main():
    print("=== Testing Title Bar Fix ===\n")

    # Show calculated values
    scale = NSScreen.mainScreen().backingScaleFactor()
    title_bar_px = _get_title_bar_height_pixels()

    print(f"Display scale: {scale}x")
    print(f"Calculated title bar height: {title_bar_px} pixels")
    print(f"In points: {title_bar_px / scale}\n")

    # List windows
    windows = get_window_list()
    print("Available windows:")
    for i, w in enumerate(windows):
        bounds = w["bounds"]
        print(f"  {i}: {w['title'][:50]} ({w['owner']}) - {int(bounds['width'])}x{int(bounds['height'])}")

    if len(sys.argv) < 2:
        print("\nUsage: python test_title_bar_fix.py <window_number>")
        return

    try:
        idx = int(sys.argv[1])
        window = windows[idx]
    except (ValueError, IndexError):
        print("Invalid choice")
        return

    print(f"\nCapturing: {window['title']}")
    print(f"Window bounds: {window['bounds']['width']}x{window['bounds']['height']} points")

    # Capture with the fixed function
    image = capture_window(window["id"])

    if image is None:
        print("Capture failed!")
        return

    # Expected size: window size * scale - title bar
    expected_width = int(window["bounds"]["width"] * scale)
    expected_height = int(window["bounds"]["height"] * scale) - title_bar_px

    print(f"\nExpected size: {expected_width}x{expected_height} pixels")
    print(f"Actual size:   {image.width}x{image.height} pixels")

    if image.width == expected_width and image.height == expected_height:
        print("✓ Size matches expected!")
    else:
        print("✗ Size mismatch!")

    # Save for visual inspection
    output_path = "/tmp/window_capture_fixed.png"
    image.save(output_path)
    print(f"\nSaved to: {output_path}")


if __name__ == "__main__":
    main()
