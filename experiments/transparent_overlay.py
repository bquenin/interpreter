#!/usr/bin/env python3
"""Test transparent overlay using X11 Shape extension.

Run with: python experiments/transparent_overlay.py

The window should appear with only the label visible - the rest should be
completely invisible and click-through.
"""

import tkinter as tk
from Xlib import X, display
from Xlib.ext import shape


class ShapedOverlay:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Shaped Overlay Test")
        self.root.geometry("800x600+200+200")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        # Use a distinct color so we can see if transparency fails
        self.root.config(bg="#FF00FF")  # Magenta - obvious if visible

        self.labels = []
        self.display = None
        self.window = None
        self._shape_applied = False

    def add_label(self, text: str, x: int, y: int):
        """Add a label at the given position."""
        label = tk.Label(
            self.root,
            text=text,
            font=("Helvetica", 20, "bold"),
            fg="white",
            bg="#404040",
            padx=8,
            pady=4,
        )
        label.place(x=x, y=y)
        self.labels.append(label)
        return label

    def apply_shape_mask(self):
        """Apply X11 shape mask to make only labels visible and click-through."""
        if self._shape_applied:
            return

        # Force full geometry update
        self.root.update()

        # Verify labels have valid geometry
        all_valid = True
        for label in self.labels:
            if label.winfo_width() == 1 or label.winfo_height() == 1:
                all_valid = False
                break

        if not all_valid:
            # Schedule retry - labels not ready yet
            print("Labels not ready, retrying in 50ms...")
            self.root.after(50, self.apply_shape_mask)
            return

        # Get X11 window - need to find the toplevel wrapper
        window_id = self.root.winfo_id()
        self.display = display.Display()
        self.window = self.display.create_resource_object('window', window_id)

        # Walk up to find the true toplevel window (Tk creates nested windows)
        toplevel = self.window
        while True:
            geom = toplevel.query_tree()
            if geom.parent == self.display.screen().root:
                break
            toplevel = geom.parent

        print(f"Tk window ID: {window_id:#x}, Toplevel ID: {toplevel.id:#x}")

        # Build list of rectangles for the shape
        rects = []
        for label in self.labels:
            lx = label.winfo_x()
            ly = label.winfo_y()
            lw = label.winfo_width()
            lh = label.winfo_height()
            rects.append((lx, ly, lw, lh))
            print(f"Label rect: x={lx}, y={ly}, w={lw}, h={lh}")

        # Apply shape using rectangles directly (simpler than pixmap)
        # shape.SO.Set = replace existing shape
        # shape.SK.Bounding = the visible boundary of the window
        toplevel.shape_rectangles(shape.SO.Set, shape.SK.Bounding, 0, 0, 0, rects)

        # Also set input shape for click-through
        toplevel.shape_rectangles(shape.SO.Set, shape.SK.Input, 0, 0, 0, rects)

        self.display.sync()

        self._shape_applied = True
        print(f"Shape mask applied to toplevel window")

    def run(self):
        """Run the overlay."""
        # Add some test labels
        self.add_label("Hello World!", 100, 100)
        self.add_label("This is a test", 200, 250)
        self.add_label("Click through me!", 50, 400)

        # Schedule shape mask application after window is mapped
        # Using after_idle ensures the mainloop has started
        self.root.after(100, self.apply_shape_mask)

        print("\nOverlay running. You should see:")
        print("- Only the label text boxes visible")
        print("- Everything else is invisible and click-through")
        print("\nPress Ctrl+C in terminal to exit")

        self.root.mainloop()

        if self.display:
            self.display.close()


if __name__ == "__main__":
    overlay = ShapedOverlay()
    overlay.run()
