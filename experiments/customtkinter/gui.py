"""CustomTkinter main GUI window with settings and controls."""

import sys
import time
import threading
from pathlib import Path
from typing import Optional
from PIL import Image, ImageTk

import customtkinter as ctk

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from interpreter.capture import WindowCapture
from .overlay import BannerOverlay, InplaceOverlay


class MainWindow(ctk.CTk):
    """Main application window using CustomTkinter."""

    def __init__(self):
        super().__init__()

        self.title("Interpreter - CustomTkinter Prototype")
        self.geometry("500x500")
        self.minsize(500, 400)

        # State
        self._capturing = False
        self._mode = "banner"
        self._windows_list: list[dict] = []
        self._capture: Optional[WindowCapture] = None

        # FPS tracking
        self._frame_count = 0
        self._fps = 0.0
        self._fps_update_time = time.time()

        # Overlays (created after mainloop starts)
        self._banner_overlay: Optional[BannerOverlay] = None
        self._inplace_overlay: Optional[InplaceOverlay] = None

        # Preview image reference (keep alive)
        self._preview_image: Optional[ImageTk.PhotoImage] = None

        self._setup_ui()
        self._refresh_windows()

        # Create overlays after window is ready
        self.after(100, self._create_overlays)

        # Capture polling
        self._poll_id: Optional[str] = None

    def _setup_ui(self):
        """Set up the main UI."""
        # Configure grid
        self.grid_columnconfigure(0, weight=1)

        # Window Selection Frame
        window_frame = ctk.CTkFrame(self)
        window_frame.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="ew")
        window_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(window_frame, text="Window Selection", font=("", 14, "bold")).grid(
            row=0, column=0, columnspan=2, padx=10, pady=(10, 5), sticky="w"
        )

        self._window_combo = ctk.CTkComboBox(window_frame, values=[], width=300)
        self._window_combo.grid(row=1, column=0, padx=10, pady=10, sticky="ew")

        refresh_btn = ctk.CTkButton(window_frame, text="Refresh", width=80, command=self._refresh_windows)
        refresh_btn.grid(row=1, column=1, padx=10, pady=10)

        # Controls Frame
        controls_frame = ctk.CTkFrame(self)
        controls_frame.grid(row=1, column=0, padx=20, pady=10, sticky="ew")

        ctk.CTkLabel(controls_frame, text="Controls", font=("", 14, "bold")).grid(
            row=0, column=0, columnspan=2, padx=10, pady=(10, 5), sticky="w"
        )

        self._start_btn = ctk.CTkButton(controls_frame, text="Start Capture", command=self._toggle_capture)
        self._start_btn.grid(row=1, column=0, padx=10, pady=10)

        self._mode_btn = ctk.CTkButton(controls_frame, text="Mode: Banner", command=self._toggle_mode)
        self._mode_btn.grid(row=1, column=1, padx=10, pady=10)

        # Status Frame
        status_frame = ctk.CTkFrame(self)
        status_frame.grid(row=2, column=0, padx=20, pady=10, sticky="ew")

        ctk.CTkLabel(status_frame, text="Status", font=("", 14, "bold")).grid(
            row=0, column=0, padx=10, pady=(10, 5), sticky="w"
        )

        self._status_label = ctk.CTkLabel(status_frame, text="Status: Idle")
        self._status_label.grid(row=1, column=0, padx=10, pady=5, sticky="w")

        self._fps_label = ctk.CTkLabel(status_frame, text="FPS: --")
        self._fps_label.grid(row=2, column=0, padx=10, pady=5, sticky="w")

        # Preview
        self._preview_label = ctk.CTkLabel(status_frame, text="No preview", width=320, height=240)
        self._preview_label.grid(row=3, column=0, padx=10, pady=10)

        # System tray note
        note_label = ctk.CTkLabel(
            self,
            text="Note: CustomTkinter doesn't have built-in system tray support",
            text_color="gray"
        )
        note_label.grid(row=3, column=0, padx=20, pady=10)

    def _create_overlays(self):
        """Create overlay windows."""
        self._banner_overlay = BannerOverlay()
        self._banner_overlay.create()
        self._banner_overlay.hide()

        self._inplace_overlay = InplaceOverlay()
        self._inplace_overlay.create()
        self._inplace_overlay.hide()

    def _refresh_windows(self):
        """Refresh the window list."""
        self._windows_list = WindowCapture.list_windows()
        titles = []
        for win in self._windows_list:
            title = win.get("title", "Unknown")
            if len(title) > 50:
                title = title[:50] + "..."
            titles.append(title)
        self._window_combo.configure(values=titles)
        if titles:
            self._window_combo.set(titles[0])

    def _toggle_capture(self):
        """Start or stop capture."""
        if self._capturing:
            self._stop_capture()
        else:
            self._start_capture()

    def _start_capture(self):
        """Start capturing the selected window."""
        selected = self._window_combo.get()
        if not selected:
            self._status_label.configure(text="Status: No window selected")
            return

        # Find matching window
        idx = -1
        for i, win in enumerate(self._windows_list):
            title = win.get("title", "")
            if title.startswith(selected.rstrip("...")):
                idx = i
                break

        if idx < 0:
            self._status_label.configure(text="Status: Window not found")
            return

        window = self._windows_list[idx]
        title = window.get("title", "")

        self._capture = WindowCapture(title)
        if not self._capture.find_window():
            self._status_label.configure(text="Status: Window not found")
            return

        if not self._capture.start_stream():
            self._status_label.configure(text="Status: Failed to start stream")
            return

        self._capturing = True
        self._frame_count = 0
        self._fps_update_time = time.time()
        self._start_btn.configure(text="Stop Capture")
        self._status_label.configure(text=f"Status: Capturing '{title[:30]}...'")

        # Show overlay
        self._show_overlay()

        # Start polling
        self._poll_capture()

    def _stop_capture(self):
        """Stop capturing."""
        if self._poll_id:
            self.after_cancel(self._poll_id)
            self._poll_id = None

        if self._capture:
            self._capture.stop_stream()
            self._capture = None

        self._capturing = False
        self._start_btn.configure(text="Start Capture")
        self._status_label.configure(text="Status: Idle")
        self._fps_label.configure(text="FPS: --")

        # Hide overlays
        if self._banner_overlay:
            self._banner_overlay.hide()
        if self._inplace_overlay:
            self._inplace_overlay.hide()

    def _toggle_mode(self):
        """Toggle between banner and inplace mode."""
        if self._mode == "banner":
            self._mode = "inplace"
            self._mode_btn.configure(text="Mode: Inplace")
        else:
            self._mode = "banner"
            self._mode_btn.configure(text="Mode: Banner")

        if self._capturing:
            self._show_overlay()

    def _show_overlay(self):
        """Show the appropriate overlay."""
        if self._mode == "banner":
            if self._inplace_overlay:
                self._inplace_overlay.hide()
            if self._banner_overlay:
                self._banner_overlay.show()
        else:
            if self._banner_overlay:
                self._banner_overlay.hide()
            if self._inplace_overlay:
                if self._capture and self._capture.bounds:
                    self._inplace_overlay.position_over_window(self._capture.bounds)
                self._inplace_overlay.show()

    def _poll_capture(self):
        """Poll for new frames."""
        if not self._capturing or not self._capture:
            return

        frame = self._capture.get_frame()
        if frame is not None:
            self._on_frame(frame)

        # Schedule next poll (~30 FPS)
        self._poll_id = self.after(33, self._poll_capture)

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
            self._fps_label.configure(text=f"FPS: {self._fps:.1f}")

        # Update preview
        preview = frame.copy()
        preview.thumbnail((320, 240))
        self._preview_image = ImageTk.PhotoImage(preview)
        self._preview_label.configure(image=self._preview_image, text="")

        # Update overlay
        if self._mode == "banner" and self._banner_overlay:
            self._banner_overlay.set_text(f"Capturing... Frame at {self._fps:.1f} FPS")
        elif self._mode == "inplace" and self._inplace_overlay:
            if self._capture and self._capture.bounds:
                self._inplace_overlay.position_over_window(self._capture.bounds)
            self._inplace_overlay.set_regions([
                {"text": "Sample text 1", "x": 50, "y": 50},
                {"text": "Another region", "x": 100, "y": 150},
            ])

    def destroy(self):
        """Clean up before destroying."""
        self._stop_capture()
        if self._banner_overlay:
            self._banner_overlay.destroy()
        if self._inplace_overlay:
            self._inplace_overlay.destroy()
        super().destroy()
