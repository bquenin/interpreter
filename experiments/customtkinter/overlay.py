"""CustomTkinter overlay windows for banner and inplace modes."""

import platform
import tkinter as tk
from typing import Optional

_system = platform.system()


class BannerOverlay:
    """Banner-style overlay at bottom of screen using tkinter."""

    def __init__(self):
        self._root: Optional[tk.Tk] = None
        self._label: Optional[tk.Label] = None
        self._drag_data = {"x": 0, "y": 0}

    def create(self):
        """Create the banner window."""
        self._root = tk.Toplevel()
        self._root.title("Banner")
        self._root.overrideredirect(True)  # Frameless
        self._root.attributes("-topmost", True)
        self._root.configure(bg="#404040")

        # Platform-specific transparency
        if _system == "Darwin":
            self._root.attributes("-transparent", False)
        elif _system == "Windows":
            pass  # No transparency needed for banner
        elif _system == "Linux":
            pass

        # Create label
        self._label = tk.Label(
            self._root,
            text="Banner Overlay - Sample Text",
            font=("Helvetica", 24, "bold"),
            fg="white",
            bg="#404040",
            wraplength=760,
            padx=20,
            pady=15
        )
        self._label.pack(fill=tk.BOTH, expand=True)

        # Size and position
        self._root.geometry("800x80")
        self._move_to_bottom()

        # Dragging bindings
        self._label.bind("<Button-1>", self._start_drag)
        self._label.bind("<B1-Motion>", self._on_drag)

    def _move_to_bottom(self):
        """Position at bottom center of screen."""
        self._root.update_idletasks()
        screen_w = self._root.winfo_screenwidth()
        screen_h = self._root.winfo_screenheight()
        win_w = self._root.winfo_width()
        win_h = self._root.winfo_height()
        x = (screen_w - win_w) // 2
        y = screen_h - win_h - 50
        self._root.geometry(f"+{x}+{y}")

    def _start_drag(self, event):
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y

    def _on_drag(self, event):
        x = self._root.winfo_x() + event.x - self._drag_data["x"]
        y = self._root.winfo_y() + event.y - self._drag_data["y"]
        self._root.geometry(f"+{x}+{y}")

    def set_text(self, text: str):
        """Update the displayed text."""
        if self._label:
            self._label.config(text=text)

    def show(self):
        if self._root:
            self._root.deiconify()

    def hide(self):
        if self._root:
            self._root.withdraw()

    def destroy(self):
        if self._root:
            self._root.destroy()
            self._root = None


class InplaceOverlay:
    """Transparent overlay for inplace text display using tkinter."""

    def __init__(self):
        self._root: Optional[tk.Toplevel] = None
        self._labels: list[tk.Label] = []
        self._canvas: Optional[tk.Canvas] = None

    def create(self):
        """Create the inplace overlay window."""
        self._root = tk.Toplevel()
        self._root.title("Inplace")
        self._root.overrideredirect(True)  # Frameless
        self._root.attributes("-topmost", True)

        # Platform-specific transparency and click-through
        if _system == "Darwin":
            # macOS: Use transparent background
            self._root.attributes("-transparent", True)
            self._root.config(bg="systemTransparent")
            # Click-through requires AppKit - simplified version
            try:
                from AppKit import NSApp, NSApplicationActivationPolicyAccessory
                NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
            except ImportError:
                pass
        elif _system == "Windows":
            # Windows: Use transparent color
            self._root.attributes("-transparentcolor", "#010101")
            self._root.config(bg="#010101")
        elif _system == "Linux":
            # Linux: RGBA transparency
            self._root.attributes("-alpha", 0.0)  # Start invisible
            self._root.config(bg="black")
            self._root.wait_visibility()
            self._root.attributes("-alpha", 1.0)

        # Canvas for positioning labels
        self._canvas = tk.Canvas(
            self._root,
            highlightthickness=0,
            bg="#010101" if _system == "Windows" else "systemTransparent" if _system == "Darwin" else "black"
        )
        self._canvas.pack(fill=tk.BOTH, expand=True)

        # Full screen by default
        screen_w = self._root.winfo_screenwidth()
        screen_h = self._root.winfo_screenheight()
        self._root.geometry(f"{screen_w}x{screen_h}+0+0")

    def set_regions(self, regions: list[dict]):
        """Update text regions."""
        # Clear old labels
        for label in self._labels:
            label.destroy()
        self._labels.clear()

        if not self._canvas:
            return

        # Create new labels
        for region in regions:
            label = tk.Label(
                self._canvas,
                text=region.get("text", ""),
                font=("Helvetica", 18, "bold"),
                fg="white",
                bg="#000000",
                padx=8,
                pady=4
            )
            # Position using place for absolute positioning
            label.place(x=region.get("x", 0), y=region.get("y", 0))
            self._labels.append(label)

    def position_over_window(self, bounds: dict):
        """Position overlay to cover a window."""
        if self._root:
            self._root.geometry(
                f"{bounds['width']}x{bounds['height']}+{bounds['x']}+{bounds['y']}"
            )

    def show(self):
        if self._root:
            self._root.deiconify()

    def hide(self):
        if self._root:
            self._root.withdraw()

    def destroy(self):
        if self._root:
            self._root.destroy()
            self._root = None
