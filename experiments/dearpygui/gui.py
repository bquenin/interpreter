"""Dear PyGui main GUI with settings and controls.

NOTE: Dear PyGui has significant limitations for overlay functionality:
- Cannot create truly transparent windows
- Cannot make windows click-through
- Uses GPU rendering (good for performance, but different paradigm)

This prototype demonstrates the settings GUI capabilities, but the overlay
would need to be implemented with a different library for production use.
"""

import sys
import time
from pathlib import Path
from typing import Optional

import dearpygui.dearpygui as dpg
import numpy as np
from PIL import Image

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from interpreter.capture import WindowCapture
from .overlay import BannerOverlay, InplaceOverlay


class MainGUI:
    """Main application GUI using Dear PyGui."""

    def __init__(self):
        # State
        self._capturing = False
        self._mode = "banner"
        self._windows_list: list[dict] = []
        self._window_titles: list[str] = []
        self._capture: Optional[WindowCapture] = None

        # FPS tracking
        self._frame_count = 0
        self._fps = 0.0
        self._fps_update_time = time.time()

        # Overlays
        self._banner_overlay = BannerOverlay()
        self._inplace_overlay = InplaceOverlay()

        # Preview texture
        self._preview_texture_id = None

    def setup(self):
        """Set up the Dear PyGui context and windows."""
        dpg.create_context()

        # Create preview texture (placeholder)
        self._create_preview_texture()

        # Main window
        with dpg.window(label="Interpreter - Dear PyGui Prototype", tag="main_window"):
            # Window Selection
            with dpg.collapsing_header(label="Window Selection", default_open=True):
                dpg.add_combo(
                    items=[],
                    tag="window_combo",
                    width=350,
                    callback=self._on_window_selected
                )
                dpg.add_button(label="Refresh", callback=self._refresh_windows)

            dpg.add_spacer(height=10)

            # Controls
            with dpg.collapsing_header(label="Controls", default_open=True):
                with dpg.group(horizontal=True):
                    dpg.add_button(
                        label="Start Capture",
                        tag="start_btn",
                        callback=self._toggle_capture
                    )
                    dpg.add_button(
                        label="Mode: Banner",
                        tag="mode_btn",
                        callback=self._toggle_mode
                    )

            dpg.add_spacer(height=10)

            # Status
            with dpg.collapsing_header(label="Status", default_open=True):
                dpg.add_text("Status: Idle", tag="status_text")
                dpg.add_text("FPS: --", tag="fps_text")

                dpg.add_spacer(height=10)

                # Preview image
                dpg.add_image(self._preview_texture_id, tag="preview_image")

            dpg.add_spacer(height=10)

            # Limitation notice
            with dpg.collapsing_header(label="Limitations", default_open=True):
                dpg.add_text(
                    "Dear PyGui cannot create transparent/click-through windows.",
                    color=(255, 200, 100)
                )
                dpg.add_text(
                    "For true overlays, use PySide6 or tkinter.",
                    color=(255, 200, 100)
                )
                dpg.add_text(
                    "No native system tray support.",
                    color=(255, 200, 100)
                )

        # Create overlay windows (within viewport)
        self._banner_overlay.create()
        self._banner_overlay.hide()
        self._inplace_overlay.create()
        self._inplace_overlay.hide()

        # Configure viewport
        dpg.create_viewport(
            title="Interpreter - Dear PyGui",
            width=550,
            height=650
        )
        dpg.setup_dearpygui()

        # Set main window as primary
        dpg.set_primary_window("main_window", True)

        # Initial refresh
        self._refresh_windows()

    def _create_preview_texture(self):
        """Create the preview texture."""
        # Create a gray placeholder image
        width, height = 320, 240
        data = np.full((height, width, 4), 42, dtype=np.float32) / 255.0
        data[:, :, 3] = 1.0  # Alpha

        with dpg.texture_registry():
            self._preview_texture_id = dpg.add_dynamic_texture(
                width=width,
                height=height,
                default_value=data.flatten().tolist(),
                tag="preview_texture"
            )

    def _update_preview_texture(self, image: Image.Image):
        """Update the preview texture with a new image."""
        # Resize to fit
        image = image.copy()
        image.thumbnail((320, 240))

        # Pad to exact size
        padded = Image.new("RGBA", (320, 240), (42, 42, 42, 255))
        x = (320 - image.width) // 2
        y = (240 - image.height) // 2
        padded.paste(image, (x, y))

        # Convert to normalized float array
        arr = np.array(padded, dtype=np.float32) / 255.0
        dpg.set_value("preview_texture", arr.flatten().tolist())

    def _refresh_windows(self):
        """Refresh the window list."""
        self._windows_list = WindowCapture.list_windows()
        self._window_titles = []
        for win in self._windows_list:
            title = win.get("title", "Unknown")
            if len(title) > 50:
                title = title[:50] + "..."
            self._window_titles.append(title)

        dpg.configure_item("window_combo", items=self._window_titles)
        if self._window_titles:
            dpg.set_value("window_combo", self._window_titles[0])

    def _on_window_selected(self, sender, app_data):
        """Handle window selection."""
        pass  # Just store selection, used when starting capture

    def _toggle_capture(self):
        """Start or stop capture."""
        if self._capturing:
            self._stop_capture()
        else:
            self._start_capture()

    def _start_capture(self):
        """Start capturing the selected window."""
        selected = dpg.get_value("window_combo")
        if not selected:
            dpg.set_value("status_text", "Status: No window selected")
            return

        # Find matching window
        idx = -1
        for i, title in enumerate(self._window_titles):
            if title == selected:
                idx = i
                break

        if idx < 0 or idx >= len(self._windows_list):
            dpg.set_value("status_text", "Status: Window not found")
            return

        window = self._windows_list[idx]
        title = window.get("title", "")

        self._capture = WindowCapture(title)
        if not self._capture.find_window():
            dpg.set_value("status_text", "Status: Window not found")
            return

        if not self._capture.start_stream():
            dpg.set_value("status_text", "Status: Failed to start stream")
            return

        self._capturing = True
        self._frame_count = 0
        self._fps_update_time = time.time()
        dpg.set_item_label("start_btn", "Stop Capture")
        dpg.set_value("status_text", f"Status: Capturing '{title[:30]}...'")

        # Show overlay
        self._show_overlay()

    def _stop_capture(self):
        """Stop capturing."""
        if self._capture:
            self._capture.stop_stream()
            self._capture = None

        self._capturing = False
        dpg.set_item_label("start_btn", "Start Capture")
        dpg.set_value("status_text", "Status: Idle")
        dpg.set_value("fps_text", "FPS: --")

        # Hide overlays
        self._banner_overlay.hide()
        self._inplace_overlay.hide()

    def _toggle_mode(self):
        """Toggle between banner and inplace mode."""
        if self._mode == "banner":
            self._mode = "inplace"
            dpg.set_item_label("mode_btn", "Mode: Inplace")
        else:
            self._mode = "banner"
            dpg.set_item_label("mode_btn", "Mode: Banner")

        if self._capturing:
            self._show_overlay()

    def _show_overlay(self):
        """Show the appropriate overlay."""
        if self._mode == "banner":
            self._inplace_overlay.hide()
            self._banner_overlay.show()
        else:
            self._banner_overlay.hide()
            if self._capture and self._capture.bounds:
                self._inplace_overlay.position_over_window(self._capture.bounds)
            self._inplace_overlay.show()

    def _poll_frame(self):
        """Poll for new frames - called each frame."""
        if not self._capturing or not self._capture:
            return

        frame = self._capture.get_frame()
        if frame is not None:
            self._on_frame(frame)

    def _on_frame(self, frame: Image.Image):
        """Handle new frame from capture."""
        # Update FPS
        self._frame_count += 1
        now = time.time()
        elapsed = now - self._fps_update_time
        if elapsed >= 1.0:
            self._fps = self._frame_count / elapsed
            self._frame_count = 0
            self._fps_update_time = now
            dpg.set_value("fps_text", f"FPS: {self._fps:.1f}")

        # Update preview
        self._update_preview_texture(frame)

        # Update overlay
        if self._mode == "banner":
            self._banner_overlay.set_text(f"Capturing... Frame at {self._fps:.1f} FPS")
        else:
            if self._capture and self._capture.bounds:
                self._inplace_overlay.position_over_window(self._capture.bounds)
            self._inplace_overlay.set_regions([
                {"text": "Sample text 1", "x": 50, "y": 50},
                {"text": "Another region", "x": 100, "y": 150},
            ])

    def run(self):
        """Run the main loop."""
        dpg.show_viewport()

        while dpg.is_dearpygui_running():
            self._poll_frame()
            dpg.render_dearpygui_frame()

        dpg.destroy_context()
