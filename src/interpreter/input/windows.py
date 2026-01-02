"""Windows keyboard input using pynput."""

from typing import Callable, Optional

from pynput import keyboard


class KeyboardListener:
    """Global keyboard listener using pynput."""

    def __init__(self, on_press: Callable[[str], None]):
        """Initialize the keyboard listener.

        Args:
            on_press: Callback function that receives the key character
                     (e.g., 'm', '=', '-', 'q') when a key is pressed.
        """
        self._on_press = on_press
        self._listener: Optional[keyboard.Listener] = None

    def _handle_key(self, key) -> None:
        """Handle key press events from pynput."""
        try:
            if hasattr(key, 'char') and key.char:
                # Regular character key (e.g., 'm', 'q', '`')
                self._on_press(key.char)
            elif hasattr(key, 'name') and key.name:
                # Special key (e.g., 'f1', 'escape', 'space')
                self._on_press(key.name)
        except AttributeError:
            pass

    def start(self) -> None:
        """Start listening for keyboard events in a background thread."""
        if self._listener is not None:
            return

        self._listener = keyboard.Listener(on_press=self._handle_key)
        self._listener.start()

    def stop(self) -> None:
        """Stop listening for keyboard events."""
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
