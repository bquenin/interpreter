"""Platform-specific permission checking."""

import platform


def is_macos() -> bool:
    """Check if running on macOS."""
    return platform.system() == "Darwin"


if platform.system() == "Darwin":
    from .macos import (
        check_accessibility,
        check_screen_recording,
        open_accessibility_settings,
        open_screen_recording_settings,
        request_accessibility,
        request_screen_recording,
    )
else:
    # Stub functions for non-macOS platforms
    def check_screen_recording() -> bool:
        return True

    def check_accessibility() -> bool:
        return True

    def request_screen_recording() -> bool:
        return True

    def request_accessibility() -> bool:
        return True

    def open_screen_recording_settings() -> None:
        pass

    def open_accessibility_settings() -> None:
        pass
