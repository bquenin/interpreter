"""Platform-agnostic keyboard listener.

Uses pynput on macOS/Windows, X11 RECORD extension on Linux.
This avoids the evdev dependency that pynput requires on Linux.
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
    # Linux: Use X11 RECORD extension (no evdev dependency)
    from Xlib import XK, X, display
    from Xlib.ext import record
    from Xlib.protocol import rq

    class Listener:
        """Global keyboard listener using X11 RECORD extension."""

        def __init__(self, on_press: Callable[[Any], None]):
            self._on_press = on_press
            self._running = False
            self._thread: threading.Thread | None = None
            self._record_display: display.Display | None = None
            self._local_display: display.Display | None = None
            self._context: int | None = None

        def start(self) -> None:
            """Start listening for keyboard events in a background thread."""
            if self._running:
                return

            self._running = True
            logger.debug("keyboard listener starting")

            try:
                self._thread = threading.Thread(target=self._listen_loop, daemon=True)
                self._thread.start()
                logger.debug("keyboard listener thread started")
            except Exception as e:
                logger.warning("keyboard shortcuts unavailable", err=str(e))

        def _listen_loop(self) -> None:
            """Background thread that captures keyboard events."""
            try:
                # Need two display connections for RECORD extension
                self._record_display = display.Display()
                self._local_display = display.Display()
                logger.debug("keyboard listener X11 displays opened")

                # Check if RECORD extension is available
                if not self._record_display.has_extension("RECORD"):
                    logger.warning("x11 record extension not available")
                    return

                logger.debug("keyboard listener RECORD extension available")

                # Create recording context for key events
                self._context = self._record_display.record_create_context(
                    0,  # datum_flags
                    [record.AllClients],  # clients
                    [
                        {
                            "core_requests": (0, 0),
                            "core_replies": (0, 0),
                            "ext_requests": (0, 0, 0, 0),
                            "ext_replies": (0, 0, 0, 0),
                            "delivered_events": (0, 0),
                            "device_events": (X.KeyPress, X.KeyRelease),
                            "errors": (0, 0),
                            "client_started": False,
                            "client_died": False,
                        }
                    ],
                )

                # Enable context and process events
                self._record_display.record_enable_context(self._context, self._handle_event)

                # This blocks until record_disable_context is called
                self._record_display.record_free_context(self._context)

            except Exception as e:
                if self._running:  # Only log if not intentionally stopped
                    logger.error("keyboard listener error", err=str(e))
            finally:
                self._cleanup()

        def _handle_event(self, reply) -> None:
            """Process recorded X11 events."""
            if reply.category != record.FromServer:
                return
            if reply.client_swapped:
                return
            if not len(reply.data) or reply.data[0] < 2:
                return

            data = reply.data
            while len(data):
                event, data = rq.EventField(None).parse_binary_value(data, self._record_display.display, None, None)

                if event.type == X.KeyPress:
                    # Get the keysym for this keycode
                    keysym = self._local_display.keycode_to_keysym(
                        event.detail,
                        0,  # No modifiers
                    )

                    # Convert keysym to key object
                    key = self._keysym_to_key(keysym)
                    logger.debug("key press detected", keysym=keysym, key=key)
                    if key and self._on_press:
                        try:
                            logger.debug("calling on_press callback")
                            self._on_press(key)
                            logger.debug("on_press callback completed")
                        except Exception as e:
                            logger.error("on_press callback error", err=str(e))

        def _keysym_to_key(self, keysym: int) -> Any | None:
            """Convert X11 keysym to Key or KeyCode object."""
            # Handle space specially (keysym 32 = 0x20)
            if keysym == 0x20:
                return Key.space

            # Handle common ASCII characters (excluding space)
            if 0x21 <= keysym <= 0x7E:
                return KeyCode(chr(keysym))

            # Handle special keys via XK mapping
            keysym_name = XK.keysym_to_string(keysym)
            if keysym_name:
                # Single character names are the character itself
                if len(keysym_name) == 1:
                    return KeyCode(keysym_name)

                name_lower = keysym_name.lower()

                # Character keys with multi-char X11 names
                char_keys = {
                    "minus": "-",
                    "equal": "=",
                    "plus": "+",
                    "grave": "`",
                    "quoteleft": "`",
                }
                if name_lower in char_keys:
                    return KeyCode(char_keys[name_lower])

                # Special keys - return Key constant strings
                special_keys = {
                    "escape": Key.esc,
                    "return": Key.enter,
                    "space": Key.space,
                    "tab": Key.tab,
                    "backspace": Key.backspace,
                    "delete": Key.delete,
                    "f1": Key.f1,
                    "f2": Key.f2,
                    "f3": Key.f3,
                    "f4": Key.f4,
                    "f5": Key.f5,
                    "f6": Key.f6,
                    "f7": Key.f7,
                    "f8": Key.f8,
                    "f9": Key.f9,
                    "f10": Key.f10,
                    "f11": Key.f11,
                    "f12": Key.f12,
                }
                if name_lower in special_keys:
                    return special_keys[name_lower]

            return None

        def stop(self) -> None:
            """Stop listening for keyboard events."""
            self._running = False

            if self._context and self._local_display:
                try:
                    self._local_display.record_disable_context(self._context)
                    self._local_display.flush()
                except Exception:
                    pass

            if self._thread:
                self._thread.join(timeout=1.0)
                self._thread = None

        def _cleanup(self) -> None:
            """Clean up X11 resources."""
            if self._record_display:
                try:
                    self._record_display.close()
                except Exception:
                    pass
                self._record_display = None

            if self._local_display:
                try:
                    self._local_display.close()
                except Exception:
                    pass
                self._local_display = None

            self._context = None

else:
    # macOS/Windows: Use pynput
    from pynput import keyboard as pynput_keyboard

    # Re-export pynput's Key and KeyCode for compatibility
    Key = pynput_keyboard.Key
    KeyCode = pynput_keyboard.KeyCode
    Listener = pynput_keyboard.Listener
