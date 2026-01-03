#!/usr/bin/env python3
"""Test if App Nap is affecting our app."""

import os
import sys
import time
import subprocess

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Check current App Nap status
print("=== App Nap Investigation ===\n")

# Get our PID
pid = os.getpid()
print(f"Our PID: {pid}")

# Check process info
result = subprocess.run(
    ["ps", "-o", "pid,stat,comm", "-p", str(pid)],
    capture_output=True, text=True
)
print(f"Process status: {result.stdout}")

# Try to disable App Nap for this process
print("\nTrying to disable App Nap...")

try:
    from Foundation import NSProcessInfo

    # Begin activity to prevent App Nap
    process_info = NSProcessInfo.processInfo()

    # NSActivityUserInitiated | NSActivityIdleSystemSleepDisabled
    # This tells macOS we're doing important work
    activity = process_info.beginActivityWithOptions_reason_(
        0x00FFFFFF,  # NSActivityUserInitiatedAllowingIdleSystemSleep
        "Real-time screen capture"
    )
    print(f"Activity token: {activity}")
    print("App Nap should now be disabled for this process.")

    # Now run a benchmark to compare
    from interpreter.capture.macos import get_window_list, capture_window

    windows = get_window_list()
    print(f"\nFound {len(windows)} windows")

    if len(sys.argv) > 1:
        idx = int(sys.argv[1])
        window = windows[idx]
        window_id = window["id"]

        print(f"\nBenchmarking with App Nap disabled: {window['title']}")

        start = time.perf_counter()
        count = 0
        for _ in range(100):
            frame = capture_window(window_id)
            if frame:
                count += 1
        elapsed = time.perf_counter() - start

        print(f"100 captures in {elapsed:.2f}s")
        print(f"FPS: {count/elapsed:.1f}")
    else:
        for i, w in enumerate(windows):
            print(f"  {i}: {w['title'][:50]}")
        print("\nUsage: python app_nap_test.py <window_number>")

    # End activity
    process_info.endActivity_(activity)

except ImportError as e:
    print(f"Could not import Foundation: {e}")
except Exception as e:
    print(f"Error: {e}")
