"""wxPython main GUI window with settings and controls."""

import sys
import time
from pathlib import Path
from typing import Optional

import wx
import wx.adv
from PIL import Image

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from interpreter.capture import WindowCapture
from .overlay import BannerOverlay, InplaceOverlay


class MainWindow(wx.Frame):
    """Main application window using wxPython."""

    def __init__(self):
        super().__init__(None, title="Interpreter - wxPython Prototype", size=(500, 550))

        # State
        self._capturing = False
        self._mode = "banner"
        self._windows_list: list[dict] = []
        self._capture: Optional[WindowCapture] = None

        # FPS tracking
        self._frame_count = 0
        self._fps = 0.0
        self._fps_update_time = time.time()

        # Overlays
        self._banner_overlay: Optional[BannerOverlay] = None
        self._inplace_overlay: Optional[InplaceOverlay] = None

        # Timer for capture polling
        self._timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_timer, self._timer)

        self._setup_ui()
        self._setup_tray()
        self._create_overlays()
        self._refresh_windows()

        # Handle close event
        self.Bind(wx.EVT_CLOSE, self._on_close)

    def _setup_ui(self):
        """Set up the main UI."""
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # Window Selection
        window_box = wx.StaticBox(panel, label="Window Selection")
        window_sizer = wx.StaticBoxSizer(window_box, wx.HORIZONTAL)

        self._window_combo = wx.ComboBox(panel, style=wx.CB_READONLY)
        self._window_combo.SetMinSize((300, -1))
        window_sizer.Add(self._window_combo, 1, wx.ALL | wx.EXPAND, 5)

        refresh_btn = wx.Button(panel, label="Refresh")
        refresh_btn.Bind(wx.EVT_BUTTON, lambda e: self._refresh_windows())
        window_sizer.Add(refresh_btn, 0, wx.ALL, 5)

        main_sizer.Add(window_sizer, 0, wx.ALL | wx.EXPAND, 10)

        # Controls
        controls_box = wx.StaticBox(panel, label="Controls")
        controls_sizer = wx.StaticBoxSizer(controls_box, wx.HORIZONTAL)

        self._start_btn = wx.Button(panel, label="Start Capture")
        self._start_btn.Bind(wx.EVT_BUTTON, lambda e: self._toggle_capture())
        controls_sizer.Add(self._start_btn, 0, wx.ALL, 5)

        self._mode_btn = wx.Button(panel, label="Mode: Banner")
        self._mode_btn.Bind(wx.EVT_BUTTON, lambda e: self._toggle_mode())
        controls_sizer.Add(self._mode_btn, 0, wx.ALL, 5)

        main_sizer.Add(controls_sizer, 0, wx.ALL | wx.EXPAND, 10)

        # Status
        status_box = wx.StaticBox(panel, label="Status")
        status_sizer = wx.StaticBoxSizer(status_box, wx.VERTICAL)

        self._status_label = wx.StaticText(panel, label="Status: Idle")
        status_sizer.Add(self._status_label, 0, wx.ALL, 5)

        self._fps_label = wx.StaticText(panel, label="FPS: --")
        status_sizer.Add(self._fps_label, 0, wx.ALL, 5)

        # Preview
        self._preview_bitmap = wx.StaticBitmap(panel, size=(320, 240))
        self._preview_bitmap.SetBackgroundColour(wx.Colour(42, 42, 42))
        status_sizer.Add(self._preview_bitmap, 0, wx.ALL | wx.ALIGN_CENTER, 10)

        main_sizer.Add(status_sizer, 1, wx.ALL | wx.EXPAND, 10)

        panel.SetSizer(main_sizer)

    def _setup_tray(self):
        """Set up system tray icon."""
        # Create a simple icon
        icon = wx.Icon()
        bmp = wx.Bitmap(32, 32)
        dc = wx.MemoryDC(bmp)
        dc.SetBackground(wx.Brush(wx.Colour(0, 139, 139)))  # Dark cyan
        dc.Clear()
        dc.SelectObject(wx.NullBitmap)
        icon.CopyFromBitmap(bmp)

        self._tray = wx.adv.TaskBarIcon()
        self._tray.SetIcon(icon, "Interpreter")

        # Tray menu
        self._tray.Bind(wx.adv.EVT_TASKBAR_LEFT_DCLICK, self._on_tray_click)
        self._tray.Bind(wx.adv.EVT_TASKBAR_RIGHT_UP, self._on_tray_right_click)

    def _on_tray_click(self, event):
        """Handle tray double-click."""
        if self.IsShown():
            self.Hide()
        else:
            self.Show()
            self.Raise()

    def _on_tray_right_click(self, event):
        """Show tray context menu."""
        menu = wx.Menu()

        show_item = menu.Append(wx.ID_ANY, "Show")
        self._tray.Bind(wx.EVT_MENU, lambda e: self.Show() or self.Raise(), show_item)

        toggle_item = menu.Append(wx.ID_ANY, "Toggle Capture")
        self._tray.Bind(wx.EVT_MENU, lambda e: self._toggle_capture(), toggle_item)

        menu.AppendSeparator()

        quit_item = menu.Append(wx.ID_EXIT, "Quit")
        self._tray.Bind(wx.EVT_MENU, lambda e: self._quit(), quit_item)

        self._tray.PopupMenu(menu)
        menu.Destroy()

    def _create_overlays(self):
        """Create overlay windows."""
        self._banner_overlay = BannerOverlay()
        self._inplace_overlay = InplaceOverlay()

    def _refresh_windows(self):
        """Refresh the window list."""
        self._windows_list = WindowCapture.list_windows()
        self._window_combo.Clear()
        for win in self._windows_list:
            title = win.get("title", "Unknown")
            if len(title) > 50:
                title = title[:50] + "..."
            self._window_combo.Append(title)
        if self._windows_list:
            self._window_combo.SetSelection(0)

    def _toggle_capture(self):
        """Start or stop capture."""
        if self._capturing:
            self._stop_capture()
        else:
            self._start_capture()

    def _start_capture(self):
        """Start capturing the selected window."""
        idx = self._window_combo.GetSelection()
        if idx < 0 or idx >= len(self._windows_list):
            self._status_label.SetLabel("Status: No window selected")
            return

        window = self._windows_list[idx]
        title = window.get("title", "")

        self._capture = WindowCapture(title)
        if not self._capture.find_window():
            self._status_label.SetLabel("Status: Window not found")
            return

        if not self._capture.start_stream():
            self._status_label.SetLabel("Status: Failed to start stream")
            return

        self._capturing = True
        self._frame_count = 0
        self._fps_update_time = time.time()
        self._start_btn.SetLabel("Stop Capture")
        self._status_label.SetLabel(f"Status: Capturing '{title[:30]}...'")

        # Show overlay
        self._show_overlay()

        # Start timer (~30 FPS)
        self._timer.Start(33)

    def _stop_capture(self):
        """Stop capturing."""
        self._timer.Stop()

        if self._capture:
            self._capture.stop_stream()
            self._capture = None

        self._capturing = False
        self._start_btn.SetLabel("Start Capture")
        self._status_label.SetLabel("Status: Idle")
        self._fps_label.SetLabel("FPS: --")

        # Hide overlays
        if self._banner_overlay:
            self._banner_overlay.Hide()
        if self._inplace_overlay:
            self._inplace_overlay.Hide()

    def _toggle_mode(self):
        """Toggle between banner and inplace mode."""
        if self._mode == "banner":
            self._mode = "inplace"
            self._mode_btn.SetLabel("Mode: Inplace")
        else:
            self._mode = "banner"
            self._mode_btn.SetLabel("Mode: Banner")

        if self._capturing:
            self._show_overlay()

    def _show_overlay(self):
        """Show the appropriate overlay."""
        if self._mode == "banner":
            if self._inplace_overlay:
                self._inplace_overlay.Hide()
            if self._banner_overlay:
                self._banner_overlay.Show()
        else:
            if self._banner_overlay:
                self._banner_overlay.Hide()
            if self._inplace_overlay:
                if self._capture and self._capture.bounds:
                    self._inplace_overlay.position_over_window(self._capture.bounds)
                self._inplace_overlay.Show()

    def _on_timer(self, event):
        """Handle timer - poll for frames."""
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
            self._fps_label.SetLabel(f"FPS: {self._fps:.1f}")

        # Update preview
        preview = frame.copy()
        preview.thumbnail((320, 240))

        # Convert PIL to wx.Bitmap
        width, height = preview.size
        wx_image = wx.Image(width, height)
        wx_image.SetData(preview.convert("RGB").tobytes())
        bitmap = wx_image.ConvertToBitmap()
        self._preview_bitmap.SetBitmap(bitmap)

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

    def _on_close(self, event):
        """Handle window close - minimize to tray."""
        self.Hide()

    def _quit(self):
        """Actually quit the application."""
        self._stop_capture()
        if self._banner_overlay:
            self._banner_overlay.Destroy()
        if self._inplace_overlay:
            self._inplace_overlay.Destroy()
        if self._tray:
            self._tray.RemoveIcon()
            self._tray.Destroy()
        self.Destroy()
        wx.GetApp().ExitMainLoop()
