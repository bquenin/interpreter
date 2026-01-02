#!/usr/bin/env python3
"""Quick benchmark of capture performance."""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from interpreter.capture.macos import get_window_list, capture_window, _is_fullscreen

windows = get_window_list()
if len(sys.argv) < 2:
    for i, w in enumerate(windows):
        print(f"{i}: {w['title'][:50]}")
    sys.exit(0)

idx = int(sys.argv[1])
window = windows[idx]
window_id = window["id"]

print(f"Window: {window['title']}")
print(f"ID: {window_id}")
print(f"Fullscreen: {_is_fullscreen(window_id)}")
print()

# Quick benchmark
start = time.perf_counter()
count = 0
for _ in range(50):
    frame = capture_window(window_id)
    if frame:
        count += 1
elapsed = time.perf_counter() - start

print(f"50 captures in {elapsed:.2f}s")
print(f"Success: {count}/50")
print(f"FPS: {count/elapsed:.1f}")
if count > 0:
    print(f"Avg time: {elapsed/count*1000:.1f}ms per frame")
