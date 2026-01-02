#!/usr/bin/env python3
"""Investigate macOS APIs for title bar height."""

from AppKit import NSWindow, NSScreen, NSTitledWindowMask, NSClosableWindowMask, NSMiniaturizableWindowMask
from Quartz import CoreGraphics as CG
import objc


def get_standard_title_bar_height():
    """Get the standard title bar height using NSWindow API."""
    # Create a content rect (0, 0, 100, 100)
    content_rect = ((0, 0), (100, 100))

    # Standard window style mask
    style_mask = NSTitledWindowMask | NSClosableWindowMask | NSMiniaturizableWindowMask

    # Get the frame rect for this content rect
    frame_rect = NSWindow.frameRectForContentRect_styleMask_(content_rect, style_mask)

    # The difference in height is the title bar height
    title_bar_height = frame_rect[1][1] - content_rect[1][1]

    return title_bar_height


def get_scale_factor():
    """Get main display scale factor."""
    return NSScreen.mainScreen().backingScaleFactor()


def main():
    print("=== macOS Title Bar Height Investigation ===\n")

    scale = get_scale_factor()
    print(f"Display scale factor: {scale}x")

    title_bar_height = get_standard_title_bar_height()
    print(f"\nStandard title bar height (points): {title_bar_height}")
    print(f"Standard title bar height (pixels at {scale}x): {title_bar_height * scale}")

    # Also check what CGWindowListCreateImage actually captures
    print("\n=== Understanding CGWindowListCreateImage ===")
    print("""
CGWindowListCreateImage with kCGWindowImageBoundsIgnoreFraming:
- Captures the window content INCLUDING the title bar
- The image size matches window bounds * scale factor
- Title bar is included in the capture

To get content-only:
- We need to crop by the title bar height
- Standard macOS title bar is ~28 points (may vary)
- With 2x display: 56 pixels to crop

However, some apps have:
- Custom title bars (taller or shorter)
- Unified title bar + toolbar
- No title bar at all (borderless windows)
""")

    # Let's also try to get window properties for a specific window
    print("\n=== Checking window properties ===")

    window_list = CG.CGWindowListCopyWindowInfo(
        CG.kCGWindowListOptionAll | CG.kCGWindowListExcludeDesktopElements,
        CG.kCGNullWindowID
    )

    for window in window_list:
        title = window.get(CG.kCGWindowName, "")
        layer = window.get(CG.kCGWindowLayer, -1)

        if layer != 0 or not title:
            continue

        if "Tales of Phantasia" in title or "OpenEmu" in title:
            print(f"\nWindow: {title}")
            print(f"  All properties:")
            for key, value in window.items():
                print(f"    {key}: {value}")


if __name__ == "__main__":
    main()
