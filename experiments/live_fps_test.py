#!/usr/bin/env python3
"""Live FPS monitoring - run while switching fullscreen."""

import os
import sys
import time

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from interpreter.capture.macos import get_window_list, capture_window, _is_fullscreen


def main():
    print("=== Live FPS Monitor ===")
    print("Switch the window between windowed and fullscreen to see FPS changes.\n")

    windows = get_window_list()
    print("Available windows:")
    for i, w in enumerate(windows):
        print(f"  {i}: {w['title'][:50]}")

    if len(sys.argv) < 2:
        print("\nUsage: python live_fps_test.py <window_number>")
        return

    try:
        idx = int(sys.argv[1])
        window = windows[idx]
    except (ValueError, IndexError):
        print("Invalid choice")
        return

    window_id = window["id"]
    print(f"\nMonitoring: {window['title']}")
    print(f"Window ID: {window_id}")
    print("\nPress Ctrl+C to stop.\n")
    print("-" * 70)

    frame_count = 0
    fail_count = 0
    last_report = time.perf_counter()
    last_capture_time = 0

    try:
        while True:
            t0 = time.perf_counter()

            # Check fullscreen status
            is_fs = _is_fullscreen(window_id)
            fs_time = (time.perf_counter() - t0) * 1000

            # Capture
            t1 = time.perf_counter()
            frame = capture_window(window_id)
            capture_time = (time.perf_counter() - t1) * 1000

            if frame:
                frame_count += 1
                size = f"{frame.width}x{frame.height}"
            else:
                fail_count += 1
                size = "FAIL"

            total_time = (time.perf_counter() - t0) * 1000
            last_capture_time = total_time

            # Report every second
            now = time.perf_counter()
            if now - last_report >= 1.0:
                elapsed = now - last_report
                fps = frame_count / elapsed
                mode = "FULLSCREEN" if is_fs else "WINDOWED"

                print(f"FPS: {fps:5.1f} | Mode: {mode:10} | "
                      f"Capture: {capture_time:5.1f}ms | FS check: {fs_time:4.1f}ms | "
                      f"Size: {size} | Fails: {fail_count}")

                frame_count = 0
                fail_count = 0
                last_report = now

            # Small sleep to not max CPU
            time.sleep(0.001)

    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
