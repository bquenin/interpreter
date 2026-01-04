# Interpreter

Offline screen translator for Japanese retro games. Captures text from any window, performs OCR, translates to English, and displays subtitles in a floating overlay.

![screenshot](screenshot.png)

## Features

- **Fully offline** - No cloud APIs, no internet required after setup
- **Free** - No API costs or subscriptions
- **Private** - Text never leaves your machine
- **Optimized for retro games** - Uses MeikiOCR, trained specifically on Japanese game text
- **Two overlay modes** - Banner (subtitle bar) or inplace (text over game)
- **Translation caching** - Fuzzy matching avoids re-translating similar text

## Requirements

- Python 3.11+ (Python 3.14 not yet supported)
- **Windows 10 version 1903+**, macOS, or Linux (X11/XWayland/Wayland)

### Linux: Native Wayland Support (Optional)

For capturing native Wayland applications (not running through XWayland), install GStreamer with PipeWire support:

**Ubuntu/Debian:**
```bash
sudo apt-get install gstreamer1.0-pipewire gir1.2-gstreamer-1.0
```

**Fedora:**
```bash
sudo dnf install gstreamer1-plugin-pipewire
```

**Arch Linux:**
```bash
sudo pacman -S gst-plugin-pipewire
```

Without these packages, the application still works but can only capture X11/XWayland windows.

## Installation

### One-liner Install

**macOS/Linux:**
```bash
curl -LsSf https://raw.githubusercontent.com/bquenin/interpreter/main/install.sh | bash
```

**Windows (PowerShell):**
```powershell
powershell -c "irm https://raw.githubusercontent.com/bquenin/interpreter/main/install.ps1 | iex"
```

Then run with `interpreter-v2`.

## Upgrading

To update to the latest version, run the install script again:

**macOS/Linux:**
```bash
curl -LsSf https://raw.githubusercontent.com/bquenin/interpreter/main/install.sh | bash
```

**Windows (PowerShell):**
```powershell
powershell -c "irm https://raw.githubusercontent.com/bquenin/interpreter/main/install.ps1 | iex"
```

## Usage

```bash
interpreter-v2
```

This opens the GUI where you can select a window to capture and configure all settings.

## Hotkeys

| Key | Action |
|-----|--------|
| `Space` | Toggle overlay on/off (configurable in GUI) |

In banner mode, you can drag the overlay to reposition it.

## Overlay Modes

### Banner Mode (default)
A subtitle bar at the bottom of the screen displaying translated text. Draggable, opaque background, centered text.

### Inplace Mode
Transparent overlay positioned over the game window. Translated text appears directly over the original Japanese text at OCR-detected positions. Click-through so you can interact with the game.

## Configuration

All settings are configured through the GUI and saved to `~/.interpreter/config.yml`.

## How It Works

1. **Screen Capture** - Captures the target window at the configured refresh rate
2. **OCR** - [MeikiOCR](https://github.com/rtr46/meikiocr) extracts Japanese text (optimized for pixel fonts)
3. **Translation** - [Sugoi V4](https://huggingface.co/entai2965/sugoi-v4-ja-en-ctranslate2) translates Japanese to English
4. **Display** - Shows translated text in the selected overlay mode

## Troubleshooting

### Poor OCR accuracy
Try adjusting the OCR confidence slider in the GUI. Lower values include more text (but may include garbage), higher values are stricter.

### Slow performance
First run downloads models (~1.5GB). Subsequent runs use cached models from `~/.cache/huggingface/`.

## What's New in v2

- **Inplace overlay mode** - Text appears directly over game text
- **Translation caching** - Fuzzy matching reduces redundant translations
- **Improved OCR** - Punctuation excluded from confidence calculation
- **Better window capture** - Excludes overlapping windows, auto-detects fullscreen
- **Multi-display support** - Overlay appears on the same display as the game
