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

    def create(self, target_bounds: Optional[dict] = None):
        """Create and configure the overlay window.

        Args:
            target_bounds: Optional dict with x, y, width, height of target window.
                          If provided, overlay will be positioned on the same display.
        """
        self._root = tk.Tk()
        self._root.title("Interpreter Subtitles")

        # Determine display bounds based on target window or use primary display
        if target_bounds:
            # Position relative to target display
            display_x = target_bounds["x"]
            display_y = target_bounds["y"]
            display_width = target_bounds["width"]
            display_height = target_bounds["height"]

            # Window dimensions - full display width
            window_width = display_width
            window_height = 100

            # Position at bottom of display
            x = display_x
            y = display_y + display_height - window_height - 50
        else:
            # Fall back to primary display
            display_width = self._root.winfo_screenwidth()
            display_height = self._root.winfo_screenheight()

            window_width = int(display_width * 0.8)
            window_height = 100

            x = (display_width - window_width) // 2
            y = display_height - window_height - 50

        geometry = f"{window_width}x{window_height}+{x}+{y}"
        print(f"  Overlay geometry: {geometry}")
        self._root.geometry(geometry)
        self._target_bounds = target_bounds

        # Configure window properties
        self._root.overrideredirect(True)  # Remove window decorations
        self._root.attributes("-topmost", True)  # Always on top

        # Platform-specific transparency
        system = platform.system()
        if system == "Darwin":
            # Make window visible on all spaces including fullscreen
            self._setup_macos_fullscreen_overlay()
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

    def _setup_macos_fullscreen_overlay(self):
        """Configure window to appear on all spaces on macOS.

        Note: This makes the overlay visible on all desktop spaces,
        but cannot make it appear over true fullscreen apps due to
        macOS architectural limitations (fullscreen apps run in their
        own dedicated Mission Control space).
        """
        try:
            from AppKit import (
                NSApplication,
                NSWindowCollectionBehaviorCanJoinAllSpaces,
                NSWindowCollectionBehaviorStationary,
            )

            self._root.update_idletasks()
            ns_app = NSApplication.sharedApplication()

            for ns_window in ns_app.windows():
                title = ns_window.title() or ""
                if "Interpreter" in title or "Subtitles" in title:
                    behavior = (
                        NSWindowCollectionBehaviorCanJoinAllSpaces |
                        NSWindowCollectionBehaviorStationary
                    )
                    ns_window.setCollectionBehavior_(behavior)

                    # Position window using NSWindow (Tkinter geometry doesn't work well on multi-monitor)
                    if self._target_bounds:
                        # NSWindow uses bottom-left origin, so convert y coordinate
                        # Get total screen height for coordinate conversion
                        frame = ns_window.frame()
                        screen = ns_window.screen()
                        if screen:
                            screen_height = screen.frame().size.height
                            # Calculate position (bottom-left origin)
                            x = self._target_bounds["x"] + (self._target_bounds["width"] - frame.size.width) / 2
                            # Convert from top-left to bottom-left coordinate system
                            y = self._target_bounds["y"] + self._target_bounds["height"] - frame.size.height - 50
                            # Flip y for NSWindow coordinate system (origin at bottom-left of main screen)
                            from AppKit import NSScreen
                            main_screen_height = NSScreen.mainScreen().frame().size.height
                            y_flipped = main_screen_height - y - frame.size.height
                            ns_window.setFrameOrigin_((x, y_flipped))
                    break
        except Exception:
            pass  # PyObjC not available or other error

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
        current_height = self._root.winfo_height()
        current_y = self._root.winfo_y()

        # Adjust position to keep bottom edge in place
        current_bottom = current_y + current_height
        new_y = current_bottom - required_height

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
