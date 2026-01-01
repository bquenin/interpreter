#!/usr/bin/env python3
"""Test script to debug font rendering in Tkinter on Linux."""

import tkinter as tk
from tkinter import font as tkfont

# The problematic text
TEST_TEXT = "Cless's father, Miguel: Yeah. How's Mom's cold?"

def main():
    root = tk.Tk()
    root.title("Font Rendering Test")

    # Mimic overlay settings
    root.overrideredirect(True)  # Remove window decorations
    root.attributes("-topmost", True)  # Always on top

    # Transparency setup (like linux.py)
    transparent_color = "#010101"
    root.config(bg=transparent_color)
    root.attributes("-transparentcolor", transparent_color)

    root.geometry("1200x600+100+100")

    # List available fonts
    available_fonts = sorted(tkfont.families())
    print(f"Available fonts ({len(available_fonts)}):")
    for f in available_fonts[:20]:
        print(f"  {f}")
    print("  ...")

    # Fonts to test
    test_fonts = [
        "Helvetica",
        "helvetica",
        "Arial",
        "Liberation Sans",
        "DejaVu Sans",
        "Nimbus Sans L",
        "FreeSans",
        "Ubuntu",
        "Noto Sans",
        "TkDefaultFont",
        "sans-serif",
    ]

    y_offset = 20
    for font_name in test_fonts:
        try:
            # Create font
            test_font = tkfont.Font(family=font_name, size=24, weight="bold")
            actual_family = test_font.actual()["family"]

            # Create label
            label = tk.Label(
                root,
                text=f"[{font_name} -> {actual_family}] {TEST_TEXT}",
                font=test_font,
                fg="#FFFFFF",
                bg="#404040",
                anchor="w",
            )
            label.place(x=10, y=y_offset)
            y_offset += 40
            print(f"Font '{font_name}' -> actual: '{actual_family}'")
        except Exception as e:
            print(f"Font '{font_name}' failed: {e}")

    # Add quit button
    quit_btn = tk.Button(root, text="Quit", command=root.quit)
    quit_btn.place(x=10, y=y_offset + 20)

    root.mainloop()

if __name__ == "__main__":
    main()
