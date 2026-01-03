#!/usr/bin/env python3
"""Test the MacOSCaptureStream directly."""

import os
import sys
import time

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from interpreter.capture.macos import get_window_list, MacOSCaptureStream, capture_window


def main():
    print("=== MacOSCaptureStream Test ===\n")

    windows = get_window_list()
    print("Available windows:")
    for i, w in enumerate(windows):
        bounds = w["bounds"]
        print(f"  {i}: {w['title'][:50]} ({w['owner']}) - {int(bounds['width'])}x{int(bounds['height'])}")

    if len(sys.argv) < 2:
        print("\nUsage: python stream_test.py <window_number>")
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

    # Test 1: Direct capture timing
    print("\n=== Test 1: Direct capture_window() timing ===")
    for i in range(5):
        t0 = time.perf_counter()
        frame = capture_window(window_id)
        elapsed = (time.perf_counter() - t0) * 1000
        if frame:
            print(f"  Capture {i+1}: {elapsed:.1f}ms, size={frame.width}x{frame.height}")
        else:
            print(f"  Capture {i+1}: FAILED")

    # Test 2: MacOSCaptureStream
    print("\n=== Test 2: MacOSCaptureStream FPS ===")
    stream = MacOSCaptureStream(window_id)
    stream.start()

    # Give it time to start
    time.sleep(0.5)

    # Count frames over 5 seconds
    start = time.perf_counter()
    frame_count = 0
    none_count = 0
    last_frame = None

    while time.perf_counter() - start < 5.0:
        frame = stream.get_frame()
        if frame is not None:
            if frame is not last_frame:
                frame_count += 1
                last_frame = frame
        else:
            none_count += 1
        time.sleep(0.01)  # Poll at 100Hz

    stream.stop()

    elapsed = time.perf_counter() - start
    fps = frame_count / elapsed
    print(f"  Unique frames: {frame_count}")
    print(f"  None returns: {none_count}")
    print(f"  Elapsed: {elapsed:.2f}s")
    print(f"  FPS: {fps:.1f}")

    # Test 3: Check if frame object changes
    print("\n=== Test 3: Frame object identity check ===")
    stream = MacOSCaptureStream(window_id)
    stream.start()
    time.sleep(0.5)

    frames_by_id = set()
    for _ in range(100):
        frame = stream.get_frame()
        if frame:
            frames_by_id.add(id(frame))
        time.sleep(0.05)

    stream.stop()
    print(f"  Unique frame objects in 100 samples: {len(frames_by_id)}")


if __name__ == "__main__":
    main()
