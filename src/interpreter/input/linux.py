"""Linux keyboard input using X11 RECORD extension.

Works on both X11 and Wayland (via XWayland) without requiring
any special permissions or build dependencies.
"""

import threading
from typing import Callable, Optional

from Xlib import X, XK, display
from Xlib.ext import record
from Xlib.protocol import rq

from .. import log

logger = log.get_logger()


class KeyboardListener:
    """Global keyboard listener using X11 RECORD extension."""

    def __init__(self, on_press: Callable[[str], None]):
        """Initialize the keyboard listener.

        Args:
            on_press: Callback function that receives the key character
                     (e.g., 'm', '=', '-', 'q') when a key is pressed.
        """
        self._on_press = on_press
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._record_display: Optional[display.Display] = None
        self._local_display: Optional[display.Display] = None
        self._context: Optional[int] = None

    def start(self) -> None:
        """Start listening for keyboard events in a background thread."""
        if self._running:
            return

        self._running = True

        try:
            self._thread = threading.Thread(target=self._listen_loop, daemon=True)
            self._thread.start()
        except Exception as e:
            logger.warning("keyboard shortcuts unavailable", err=str(e))

    def _listen_loop(self) -> None:
        """Background thread that captures keyboard events."""
        try:
            # Need two display connections for RECORD extension
            self._record_display = display.Display()
            self._local_display = display.Display()

            # Check if RECORD extension is available
            if not self._record_display.has_extension("RECORD"):
                logger.warning("x11 record extension not available")
                return

            # Create recording context for key events
            self._context = self._record_display.record_create_context(
                0,  # datum_flags
                [record.AllClients],  # clients
                [{
                    'core_requests': (0, 0),
                    'core_replies': (0, 0),
                    'ext_requests': (0, 0, 0, 0),
                    'ext_replies': (0, 0, 0, 0),
                    'delivered_events': (0, 0),
                    'device_events': (X.KeyPress, X.KeyRelease),
                    'errors': (0, 0),
                    'client_started': False,
                    'client_died': False,
                }]
            )

            # Enable context and process events
            self._record_display.record_enable_context(
                self._context,
                self._handle_event
            )

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
            event, data = rq.EventField(None).parse_binary_value(
                data,
                self._record_display.display,
                None,
                None
            )

            if event.type == X.KeyPress:
                # Get the keysym for this keycode
                keysym = self._local_display.keycode_to_keysym(
                    event.detail,
                    0  # No modifiers
                )

                # Convert keysym to character
                char = self._keysym_to_char(keysym)
                if char and self._on_press:
                    try:
                        self._on_press(char)
                    except Exception:
                        pass  # Don't crash on callback errors

    def _keysym_to_char(self, keysym: int) -> Optional[str]:
        """Convert X11 keysym to character string."""
        # Handle common ASCII characters
        if 0x20 <= keysym <= 0x7e:
            return chr(keysym)

        # Handle special keys via XK mapping
        keysym_name = XK.keysym_to_string(keysym)
        if keysym_name:
            # Single character names are the character itself
            if len(keysym_name) == 1:
                return keysym_name
            # Map special key names
            special_keys = {
                'minus': '-',
                'equal': '=',
                'plus': '+',
            }
            return special_keys.get(keysym_name.lower())

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
