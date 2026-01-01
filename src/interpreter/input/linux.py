"""Linux keyboard input using pynput.

Uses pynput with evdev backend for global keyboard capture.
Requires:
- Build tools for evdev compilation (build-essential/gcc)
- User in 'input' group for Wayland
"""

import grp
import os
from typing import Callable, Optional

from pynput import keyboard as pynput_keyboard


def _is_wayland() -> bool:
    """Check if running on Wayland."""
    return bool(os.environ.get("WAYLAND_DISPLAY"))


def _in_input_group() -> bool:
    """Check if user is in the input group."""
    try:
        input_gid = grp.getgrnam("input").gr_gid
        return input_gid in os.getgroups()
    except (KeyError, OSError):
        return False


class KeyboardListener:
    """Global keyboard listener using pynput."""

    def __init__(self, on_press: Callable[[str], None]):
        """Initialize the keyboard listener.

        Args:
            on_press: Callback function that receives the key character
                     (e.g., 'm', '=', '-', 'q') when a key is pressed.
        """
        self._on_press = on_press
        self._listener: Optional[pynput_keyboard.Listener] = None

    def start(self) -> None:
        """Start listening for keyboard events in a background thread."""
        if self._listener is not None:
            return

        # Check prerequisites on Wayland
        if _is_wayland() and not _in_input_group():
            print("\nWarning: Keyboard shortcuts unavailable on Wayland")
            print("  To fix: sudo usermod -a -G input $USER (then log out/in)")
            return

        def on_press(key):
            try:
                # Get character from key
                if hasattr(key, 'char') and key.char:
                    char = key.char
                else:
                    # Handle special keys
                    key_name = str(key).replace("Key.", "")
                    special = {'minus': '-', 'equal': '='}
                    char = special.get(key_name)

                if char and self._on_press:
                    self._on_press(char)
            except Exception:
                pass

        try:
            self._listener = pynput_keyboard.Listener(on_press=on_press)
            self._listener.start()
        except Exception as e:
            print(f"\nWarning: Keyboard shortcuts failed: {e}")

    def stop(self) -> None:
        """Stop listening for keyboard events."""
        if self._listener:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None
