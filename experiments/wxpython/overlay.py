"""wxPython overlay windows for banner and inplace modes."""

import platform
import wx

_system = platform.system()


class BannerOverlay(wx.Frame):
    """Banner-style overlay at bottom of screen using wxPython."""

    def __init__(self):
        style = wx.FRAME_NO_TASKBAR | wx.STAY_ON_TOP | wx.BORDER_NONE
        super().__init__(None, title="Banner", style=style)

        self._drag_pos = None
        self._setup_ui()
        self._move_to_bottom()

        # Bind mouse events for dragging
        self.Bind(wx.EVT_LEFT_DOWN, self._on_mouse_down)
        self.Bind(wx.EVT_LEFT_UP, self._on_mouse_up)
        self.Bind(wx.EVT_MOTION, self._on_mouse_move)
        self._text.Bind(wx.EVT_LEFT_DOWN, self._on_mouse_down)
        self._text.Bind(wx.EVT_LEFT_UP, self._on_mouse_up)
        self._text.Bind(wx.EVT_MOTION, self._on_mouse_move)

    def _setup_ui(self):
        """Set up the UI."""
        self.SetBackgroundColour(wx.Colour(64, 64, 64))
        self.SetSize(800, 80)

        sizer = wx.BoxSizer(wx.VERTICAL)

        self._text = wx.StaticText(
            self,
            label="Banner Overlay - Sample Text",
            style=wx.ALIGN_CENTER_HORIZONTAL
        )
        self._text.SetForegroundColour(wx.WHITE)
        font = self._text.GetFont()
        font.SetPointSize(24)
        font.SetWeight(wx.FONTWEIGHT_BOLD)
        self._text.SetFont(font)

        sizer.AddStretchSpacer()
        sizer.Add(self._text, 0, wx.ALIGN_CENTER | wx.ALL, 10)
        sizer.AddStretchSpacer()

        self.SetSizer(sizer)

    def _move_to_bottom(self):
        """Position at bottom center of screen."""
        display = wx.Display(0)
        screen = display.GetClientArea()
        size = self.GetSize()
        x = (screen.width - size.width) // 2
        y = screen.height - size.height - 50
        self.SetPosition((x, y))

    def _on_mouse_down(self, event):
        self._drag_pos = event.GetPosition()
        self.CaptureMouse()

    def _on_mouse_up(self, event):
        if self.HasCapture():
            self.ReleaseMouse()
        self._drag_pos = None

    def _on_mouse_move(self, event):
        if event.Dragging() and event.LeftIsDown() and self._drag_pos:
            pos = self.ClientToScreen(event.GetPosition())
            self.SetPosition((pos.x - self._drag_pos.x, pos.y - self._drag_pos.y))

    def set_text(self, text: str):
        """Update the displayed text."""
        self._text.SetLabel(text)
        self.Layout()


class InplaceOverlay(wx.Frame):
    """Transparent overlay for inplace text display using wxPython."""

    def __init__(self):
        style = wx.FRAME_NO_TASKBAR | wx.STAY_ON_TOP | wx.BORDER_NONE
        super().__init__(None, title="Inplace", style=style)

        self._labels: list[wx.StaticText] = []
        self._setup_window()

        # Panel for positioning
        self._panel = wx.Panel(self)
        self._panel.SetBackgroundColour(wx.Colour(0, 0, 0, 0))

    def _setup_window(self):
        """Configure window for transparency."""
        if _system == "Darwin":
            # macOS transparency
            self.SetBackgroundColour(wx.Colour(0, 0, 0, 0))
            self.SetTransparent(254)  # 254 = almost fully transparent
        elif _system == "Windows":
            # Windows: Use layered window
            self.SetBackgroundColour(wx.Colour(1, 1, 1))
            # Need to use SetTransparent or extended styles
            self.SetTransparent(254)
        elif _system == "Linux":
            # Linux: RGBA transparency
            self.SetBackgroundColour(wx.Colour(0, 0, 0, 0))
            self.SetTransparent(254)

        # Full screen by default
        display = wx.Display(0)
        screen = display.GetClientArea()
        self.SetSize(screen.width, screen.height)
        self.SetPosition((0, 0))

    def set_regions(self, regions: list[dict]):
        """Update text regions."""
        # Clear old labels
        for label in self._labels:
            label.Destroy()
        self._labels.clear()

        # Create new labels
        for region in regions:
            label = wx.StaticText(
                self._panel,
                label=region.get("text", ""),
                pos=(region.get("x", 0), region.get("y", 0))
            )
            label.SetForegroundColour(wx.WHITE)
            label.SetBackgroundColour(wx.Colour(0, 0, 0, 180))
            font = label.GetFont()
            font.SetPointSize(18)
            font.SetWeight(wx.FONTWEIGHT_BOLD)
            label.SetFont(font)
            self._labels.append(label)

    def position_over_window(self, bounds: dict):
        """Position overlay to cover a window."""
        self.SetPosition((bounds["x"], bounds["y"]))
        self.SetSize(bounds["width"], bounds["height"])
        self._panel.SetSize(bounds["width"], bounds["height"])
