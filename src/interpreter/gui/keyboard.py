"""Platform-agnostic keyboard listener.

Uses pynput on macOS/Windows, evdev on Linux (works on both X11 and Wayland).
"""

import platform
import threading
from collections.abc import Callable
from typing import Any

from .. import log

logger = log.get_logger()

_system = platform.system()


class Key:
    """Key constants compatible with pynput.keyboard.Key."""

    space = "space"
    esc = "escape"
    tab = "tab"
    enter = "enter"
    backspace = "backspace"
    delete = "delete"
    home = "home"
    end = "end"
    page_up = "page_up"
    page_down = "page_down"
    up = "up"
    down = "down"
    left = "left"
    right = "right"
    f1 = "f1"
    f2 = "f2"
    f3 = "f3"
    f4 = "f4"
    f5 = "f5"
    f6 = "f6"
    f7 = "f7"
    f8 = "f8"
    f9 = "f9"
    f10 = "f10"
    f11 = "f11"
    f12 = "f12"


class KeyCode:
    """Represents a single character key."""

    def __init__(self, char: str):
        self.char = char

    @classmethod
    def from_char(cls, char: str) -> "KeyCode":
        return cls(char)

    def __eq__(self, other):
        if isinstance(other, KeyCode):
            return self.char == other.char
        if isinstance(other, str):
            return self.char == other
        return False

    def __hash__(self):
        return hash(self.char)

    def __repr__(self):
        return f"KeyCode({self.char!r})"


if _system == "Linux":
    # Linux: Use evdev for global hotkeys (works on both X11 and Wayland)
    import evdev
    from evdev import ecodes

    # Map evdev keycodes to Key constants
    _EVDEV_KEY_MAP = {
        ecodes.KEY_SPACE: Key.space,
        ecodes.KEY_ESC: Key.esc,
        ecodes.KEY_TAB: Key.tab,
        ecodes.KEY_ENTER: Key.enter,
        ecodes.KEY_BACKSPACE: Key.backspace,
        ecodes.KEY_DELETE: Key.delete,
        ecodes.KEY_HOME: Key.home,
        ecodes.KEY_END: Key.end,
        ecodes.KEY_PAGEUP: Key.page_up,
        ecodes.KEY_PAGEDOWN: Key.page_down,
        ecodes.KEY_UP: Key.up,
        ecodes.KEY_DOWN: Key.down,
        ecodes.KEY_LEFT: Key.left,
        ecodes.KEY_RIGHT: Key.right,
        ecodes.KEY_F1: Key.f1,
        ecodes.KEY_F2: Key.f2,
        ecodes.KEY_F3: Key.f3,
        ecodes.KEY_F4: Key.f4,
        ecodes.KEY_F5: Key.f5,
        ecodes.KEY_F6: Key.f6,
        ecodes.KEY_F7: Key.f7,
        ecodes.KEY_F8: Key.f8,
        ecodes.KEY_F9: Key.f9,
        ecodes.KEY_F10: Key.f10,
        ecodes.KEY_F11: Key.f11,
        ecodes.KEY_F12: Key.f12,
    }

    # Map evdev keycodes to characters
    _EVDEV_CHAR_MAP = {
        ecodes.KEY_A: "a",
        ecodes.KEY_B: "b",
        ecodes.KEY_C: "c",
        ecodes.KEY_D: "d",
        ecodes.KEY_E: "e",
        ecodes.KEY_F: "f",
        ecodes.KEY_G: "g",
        ecodes.KEY_H: "h",
        ecodes.KEY_I: "i",
        ecodes.KEY_J: "j",
        ecodes.KEY_K: "k",
        ecodes.KEY_L: "l",
        ecodes.KEY_M: "m",
        ecodes.KEY_N: "n",
        ecodes.KEY_O: "o",
        ecodes.KEY_P: "p",
        ecodes.KEY_Q: "q",
        ecodes.KEY_R: "r",
        ecodes.KEY_S: "s",
        ecodes.KEY_T: "t",
        ecodes.KEY_U: "u",
        ecodes.KEY_V: "v",
        ecodes.KEY_W: "w",
        ecodes.KEY_X: "x",
        ecodes.KEY_Y: "y",
        ecodes.KEY_Z: "z",
        ecodes.KEY_0: "0",
        ecodes.KEY_1: "1",
        ecodes.KEY_2: "2",
        ecodes.KEY_3: "3",
        ecodes.KEY_4: "4",
        ecodes.KEY_5: "5",
        ecodes.KEY_6: "6",
        ecodes.KEY_7: "7",
        ecodes.KEY_8: "8",
        ecodes.KEY_9: "9",
        ecodes.KEY_MINUS: "-",
        ecodes.KEY_EQUAL: "=",
        ecodes.KEY_GRAVE: "`",
    }

    class Listener:
        """Global keyboard listener using evdev (works on X11 and Wayland)."""

        def __init__(self, on_press: Callable[[Any], None]):
            self._on_press = on_press
            self._running = False
            self._thread: threading.Thread | None = None
            self._devices: list[evdev.InputDevice] = []

        def start(self) -> None:
            """Start listening for keyboard events in a background thread."""
            if self._running:
                return

            self._running = True
            logger.debug("keyboard listener starting")

            try:
                self._thread = threading.Thread(target=self._listen_loop, daemon=True)
                self._thread.start()
            except Exception as e:
                logger.warning("keyboard listener failed to start", err=str(e))

        def _find_keyboards(self) -> list[evdev.InputDevice]:
            """Find all keyboard devices."""
            keyboards = []
            try:
                for path in evdev.list_devices():
                    try:
                        device = evdev.InputDevice(path)
                        caps = device.capabilities()
                        # Check if device has key events and typical keyboard keys
                        if ecodes.EV_KEY in caps:
                            keys = caps[ecodes.EV_KEY]
                            # Check for space key as indicator of keyboard
                            if ecodes.KEY_SPACE in keys:
                                keyboards.append(device)
                                logger.debug("keyboard found", device=device.name, path=device.path)
                    except (PermissionError, OSError) as e:
                        logger.debug("cannot access device", path=path, err=str(e))
            except Exception as e:
                logger.warning("failed to enumerate devices", err=str(e))
            return keyboards

        def _listen_loop(self) -> None:
            """Background thread that captures keyboard events."""
            import select

            try:
                self._devices = self._find_keyboards()
                if not self._devices:
                    logger.warning("no keyboards found - hotkeys will not work (are you in the 'input' group?)")
                    return

                logger.debug("keyboard listener started", devices=len(self._devices))

                # Create a selector for all keyboard devices
                while self._running:
                    # Wait for events on any device (with timeout for clean shutdown)
                    r, _, _ = select.select(self._devices, [], [], 0.5)
                    for device in r:
                        try:
                            for event in device.read():
                                if event.type == ecodes.EV_KEY and event.value == 1:  # Key down
                                    key = self._evdev_to_key(event.code)
                                    if key and self._on_press:
                                        try:
                                            self._on_press(key)
                                        except Exception as e:
                                            logger.error("on_press callback error", err=str(e))
                        except OSError:
                            # Device disconnected
                            pass

            except Exception as e:
                if self._running:
                    logger.error("keyboard listener error", err=str(e))
            finally:
                self._cleanup()

        def _evdev_to_key(self, code: int) -> Any | None:
            """Convert evdev keycode to Key or KeyCode object."""
            # Check special keys first
            if code in _EVDEV_KEY_MAP:
                return _EVDEV_KEY_MAP[code]

            # Check character keys
            if code in _EVDEV_CHAR_MAP:
                return KeyCode(_EVDEV_CHAR_MAP[code])

            return None

        def stop(self) -> None:
            """Stop listening for keyboard events."""
            self._running = False

            if self._thread:
                self._thread.join(timeout=1.0)
                self._thread = None

        def _cleanup(self) -> None:
            """Clean up device handles."""
            for device in self._devices:
                try:
                    device.close()
                except Exception:
                    pass
            self._devices = []
            logger.debug("keyboard listener stopped")

else:
    # macOS/Windows: Use pynput
    from pynput import keyboard as pynput_keyboard

    # Re-export pynput's Key and KeyCode for compatibility
    Key = pynput_keyboard.Key
    KeyCode = pynput_keyboard.KeyCode
    Listener = pynput_keyboard.Listener
