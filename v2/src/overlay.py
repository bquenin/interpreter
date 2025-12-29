"""Transparent overlay window for displaying subtitles."""

import platform
import tkinter as tk
from tkinter import font as tkfont
from typing import Optional


class SubtitleOverlay:
    """A transparent, always-on-top window for displaying subtitles."""

    def __init__(
        self,
        font_size: int = 24,
        font_color: str = "#FFFFFF",
        background_color: str = "#000000",
        background_opacity: float = 0.7,
    ):
        """Initialize the subtitle overlay.

        Args:
            font_size: Font size in pixels.
            font_color: Font color as hex string (e.g., "#FFFFFF").
            background_color: Background color as hex string.
            background_opacity: Background opacity (0.0 to 1.0).
        """
        self.font_size = font_size
        self.font_color = font_color
        self.background_color = background_color
        self.background_opacity = background_opacity

        self._root: Optional[tk.Tk] = None
        self._label: Optional[tk.Label] = None
        self._current_text: str = ""
        self._is_visible: bool = False

    def create(self):
        """Create and configure the overlay window."""
        self._root = tk.Tk()
        self._root.title("Interpreter Subtitles")

        # Get screen dimensions
        screen_width = self._root.winfo_screenwidth()
        screen_height = self._root.winfo_screenheight()

        # Window dimensions
        window_width = int(screen_width * 0.8)
        window_height = 100

        # Position at bottom center of screen
        x = (screen_width - window_width) // 2
        y = screen_height - window_height - 50  # 50px from bottom

        self._root.geometry(f"{window_width}x{window_height}+{x}+{y}")

        # Configure window properties
        self._root.overrideredirect(True)  # Remove window decorations
        self._root.attributes("-topmost", True)  # Always on top

        # Platform-specific transparency
        system = platform.system()
        if system == "Darwin":
            # macOS transparency
            self._root.attributes("-transparent", True)
            self._root.config(bg="systemTransparent")
            bg_with_alpha = self.background_color
        elif system == "Windows":
            # Windows transparency using a specific color as transparent
            # We'll use a magenta color as the transparent key
            transparent_color = "#FF00FF"
            self._root.attributes("-transparentcolor", transparent_color)
            self._root.config(bg=transparent_color)
            bg_with_alpha = self.background_color
        else:
            # Linux/other - try basic transparency
            self._root.attributes("-alpha", self.background_opacity)
            bg_with_alpha = self.background_color

        # Create frame for the subtitle with background
        self._frame = tk.Frame(
            self._root,
            bg=self.background_color,
            padx=20,
            pady=10,
        )
        self._frame.pack(expand=True, fill=tk.BOTH)

        # Set frame opacity on macOS
        if system == "Darwin":
            # For macOS, we need to handle transparency differently
            # The frame will have the background color
            pass

        # Create font
        subtitle_font = tkfont.Font(
            family="Helvetica",
            size=self.font_size,
            weight="bold"
        )

        # Create label for text
        self._label = tk.Label(
            self._frame,
            text="",
            font=subtitle_font,
            fg=self.font_color,
            bg=self.background_color,
            wraplength=window_width - 60,  # Account for padding
            justify=tk.CENTER,
        )
        self._label.pack(expand=True)

        # Allow dragging the window
        self._frame.bind("<Button-1>", self._start_drag)
        self._frame.bind("<B1-Motion>", self._on_drag)
        self._label.bind("<Button-1>", self._start_drag)
        self._label.bind("<B1-Motion>", self._on_drag)

        # Keyboard shortcuts
        self._root.bind("<Escape>", lambda e: self.hide())
        self._root.bind("q", lambda e: self.quit())

        self._is_visible = True

    def _start_drag(self, event):
        """Start dragging the window."""
        self._drag_start_x = event.x
        self._drag_start_y = event.y

    def _on_drag(self, event):
        """Handle window dragging."""
        x = self._root.winfo_x() + event.x - self._drag_start_x
        y = self._root.winfo_y() + event.y - self._drag_start_y
        self._root.geometry(f"+{x}+{y}")

    def update_text(self, text: str):
        """Update the displayed subtitle text.

        Args:
            text: Text to display.
        """
        if self._label is None:
            return

        self._current_text = text
        self._label.config(text=text)

        # Auto-resize height based on content
        self._root.update_idletasks()
        required_height = self._label.winfo_reqheight() + 30  # Add padding
        current_width = self._root.winfo_width()
        current_x = self._root.winfo_x()
        current_y = self._root.winfo_y()

        # Adjust position to keep bottom edge in place
        screen_height = self._root.winfo_screenheight()
        new_y = screen_height - required_height - 50

        self._root.geometry(f"{current_width}x{required_height}+{current_x}+{new_y}")

    def show(self):
        """Show the overlay window."""
        if self._root:
            self._root.deiconify()
            self._is_visible = True

    def hide(self):
        """Hide the overlay window."""
        if self._root:
            self._root.withdraw()
            self._is_visible = False

    def toggle(self):
        """Toggle overlay visibility."""
        if self._is_visible:
            self.hide()
        else:
            self.show()

    def quit(self):
        """Close the overlay and quit the application."""
        if self._root:
            self._root.quit()
            self._root.destroy()

    def update(self):
        """Process pending Tkinter events (call this in main loop)."""
        if self._root:
            self._root.update()

    def mainloop(self):
        """Start the Tkinter main loop (blocks until window closed)."""
        if self._root:
            self._root.mainloop()

    @property
    def is_running(self) -> bool:
        """Check if the overlay window is still running."""
        try:
            if self._root:
                self._root.winfo_exists()
                return True
        except tk.TclError:
            pass
        return False
