#!/usr/bin/env python3
"""Test if window ID changes when going fullscreen."""

import os
import sys
import time

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from interpreter.capture.macos import get_window_list, capture_window
from Quartz import CoreGraphics as CG


def get_window_info_by_id(window_id: int):
    """Get window info by ID."""
    window_list = CG.CGWindowListCopyWindowInfo(
        CG.kCGWindowListOptionAll,
        CG.kCGNullWindowID
    )
    for window in window_list:
        if window.get(CG.kCGWindowNumber) == window_id:
            return window
    return None


def main():
    print("=== Window ID Persistence Test ===\n")
    print("This test monitors a window to see if its ID changes.")
    print("Try switching the window to fullscreen during the test.\n")

    windows = get_window_list()
    print("Available windows:")
    for i, w in enumerate(windows):
        print(f"  {i}: {w['title'][:50]} ({w['owner']})")

    if len(sys.argv) < 2:
        print("\nUsage: python window_id_test.py <window_number>")
        return

    try:
        idx = int(sys.argv[1])
        window = windows[idx]
    except (ValueError, IndexError):
        print("Invalid choice")
        return

    window_id = window["id"]
    window_title = window["title"]
    print(f"\nMonitoring: {window_title}")
    print(f"Initial Window ID: {window_id}")
    print("\nMonitoring for 30 seconds... (switch to fullscreen now)")
    print("-" * 60)

    start = time.time()
    last_found_id = window_id
    id_changes = []

    while time.time() - start < 30:
        # Check if original ID still exists
        info = get_window_info_by_id(window_id)
        original_exists = info is not None

        # Search for window by title
        windows = get_window_list()
        matching = [w for w in windows if window_title in w["title"]]

        # Try to capture the original ID
        frame = capture_window(window_id)
        capture_ok = frame is not None

        status = []
        if not original_exists:
            status.append("ID_GONE")
        if not capture_ok:
            status.append("CAPTURE_FAIL")

        if matching:
            current_id = matching[0]["id"]
            if current_id != last_found_id:
                id_changes.append((time.time() - start, last_found_id, current_id))
                last_found_id = current_id
                status.append(f"ID_CHANGED: {current_id}")
            current_bounds = matching[0]["bounds"]
            status.append(f"size={current_bounds['width']}x{current_bounds['height']}")
        else:
            status.append("NOT_FOUND")

        elapsed = time.time() - start
        print(f"[{elapsed:5.1f}s] original_id={window_id} exists={original_exists} "
              f"capture={capture_ok} {' '.join(status)}")

        time.sleep(1)

    print("-" * 60)
    if id_changes:
        print(f"\nWindow ID changed {len(id_changes)} time(s):")
        for t, old, new in id_changes:
            print(f"  At {t:.1f}s: {old} -> {new}")
    else:
        print("\nWindow ID remained constant.")


if __name__ == "__main__":
    main()
