"""macOS permission checking and requesting."""

import subprocess


def check_screen_recording() -> bool:
    """Check if Screen Recording permission is granted.

    Returns:
        True if permission is granted, False otherwise.
    """
    try:
        import Quartz.CoreGraphics as CG

        return CG.CGPreflightScreenCaptureAccess()
    except Exception:
        return False


def check_accessibility() -> bool:
    """Check if Accessibility permission is granted.

    This is required for global hotkeys (pynput uses Quartz event taps).

    Returns:
        True if permission is granted, False otherwise.
    """
    try:
        from ApplicationServices import AXIsProcessTrusted

        return AXIsProcessTrusted()
    except Exception:
        return False


def request_screen_recording() -> bool:
    """Request Screen Recording permission.

    This will trigger the system permission dialog if the user
    hasn't been prompted before. If already denied, it won't
    re-prompt - user must go to System Settings.

    Returns:
        True if permission is granted, False otherwise.
    """
    try:
        import Quartz.CoreGraphics as CG

        return CG.CGRequestScreenCaptureAccess()
    except Exception:
        return False


def request_accessibility() -> bool:
    """Request Accessibility permission.

    This will prompt the user to grant accessibility access.
    Required for global hotkeys.

    Returns:
        True if permission is granted, False otherwise.
    """
    try:
        from ApplicationServices import AXIsProcessTrustedWithOptions
        from Foundation import NSDictionary

        # kAXTrustedCheckOptionPrompt = True will show the prompt
        options = NSDictionary.dictionaryWithObject_forKey_(True, "AXTrustedCheckOptionPrompt")
        return AXIsProcessTrustedWithOptions(options)
    except Exception:
        return False


def open_screen_recording_settings() -> None:
    """Open System Settings to the Screen Recording pane."""
    subprocess.run(
        ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"], check=False
    )


def open_accessibility_settings() -> None:
    """Open System Settings to the Accessibility pane."""
    subprocess.run(
        ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"],
        check=False,
    )
