"""Dear PyGui overlay implementation.

NOTE: Dear PyGui doesn't support transparent/click-through windows natively.
This module demonstrates what's possible, but overlays are limited.

For true transparent overlays, Dear PyGui would need to be combined with
another windowing library (e.g., using DPG for the main GUI and tkinter/Qt
for the overlay).
"""

import dearpygui.dearpygui as dpg


class BannerOverlay:
    """Banner overlay using Dear PyGui viewport.

    Note: DPG viewports cannot be made transparent or click-through.
    This is a limitation of the library for overlay use cases.
    """

    def __init__(self):
        self._viewport_created = False
        self._text = "Banner Overlay - Sample Text"

    def create(self):
        """Create the banner window.

        Note: Dear PyGui uses a single viewport model, so this creates
        a child window within the main viewport instead of a separate window.
        """
        with dpg.window(
            label="Banner Overlay",
            tag="banner_window",
            no_title_bar=True,
            no_resize=True,
            no_move=False,  # Allow dragging
            no_collapse=True,
            width=800,
            height=80,
            pos=[100, 500],
        ):
            dpg.add_text(
                self._text,
                tag="banner_text",
                color=(255, 255, 255),
            )

    def set_text(self, text: str):
        """Update the displayed text."""
        self._text = text
        if dpg.does_item_exist("banner_text"):
            dpg.set_value("banner_text", text)

    def show(self):
        if dpg.does_item_exist("banner_window"):
            dpg.show_item("banner_window")

    def hide(self):
        if dpg.does_item_exist("banner_window"):
            dpg.hide_item("banner_window")


class InplaceOverlay:
    """Inplace overlay using Dear PyGui.

    LIMITATION: Dear PyGui cannot create transparent, click-through windows.
    This implementation shows text in a child window, but it won't work
    as a true game overlay.

    For real game overlays, you would need to:
    1. Use DPG for the settings GUI
    2. Use a separate library (Qt/tkinter) for the transparent overlay
    """

    def __init__(self):
        self._regions: list[dict] = []

    def create(self):
        """Create the inplace window."""
        with dpg.window(
            label="Inplace Overlay",
            tag="inplace_window",
            no_title_bar=True,
            no_resize=True,
            no_move=True,
            no_collapse=True,
            no_background=True,  # Closest to "transparent" but still captures input
            width=800,
            height=600,
            pos=[0, 0],
        ):
            # Container for text items
            dpg.add_group(tag="inplace_group")

    def set_regions(self, regions: list[dict]):
        """Update text regions."""
        self._regions = regions

        if not dpg.does_item_exist("inplace_group"):
            return

        # Clear existing items
        dpg.delete_item("inplace_group", children_only=True)

        # Add new text items
        for i, region in enumerate(regions):
            dpg.add_text(
                region.get("text", ""),
                parent="inplace_group",
                tag=f"inplace_text_{i}",
                color=(255, 255, 255),
                pos=[region.get("x", 0), region.get("y", 0)],
            )

    def position_over_window(self, bounds: dict):
        """Position overlay to cover a window."""
        if dpg.does_item_exist("inplace_window"):
            dpg.set_item_pos("inplace_window", [bounds["x"], bounds["y"]])
            dpg.set_item_width("inplace_window", bounds["width"])
            dpg.set_item_height("inplace_window", bounds["height"])

    def show(self):
        if dpg.does_item_exist("inplace_window"):
            dpg.show_item("inplace_window")

    def hide(self):
        if dpg.does_item_exist("inplace_window"):
            dpg.hide_item("inplace_window")
