# Interpreter

Offline screen translator for Japanese retro games. Captures text from any window, performs OCR, translates to English, and displays subtitles in a floating overlay.

![sample](sample.jpg)

## Features

- **Fully offline** - No cloud APIs, no internet required after setup
- **Free** - No API costs or subscriptions
- **Private** - Text never leaves your machine
- **Optimized for retro games** - Uses MeikiOCR, trained specifically on Japanese game text

## Requirements

- Python 3.11+
- macOS or Windows

## Installation

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/) (modern Python package manager):
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. Clone and install:
   ```bash
   git clone https://github.com/bquenin/interpreter.git
   cd interpreter
   uv sync
   ```

3. Models are downloaded automatically on first run (~1.5GB total).

## Usage

```bash
# List available windows
uv run interpreter --list-windows

# Run with default config
uv run interpreter

# Run with specific window
uv run interpreter --window "Tales"

# Debug mode (show OCR confidence scores)
uv run interpreter --debug
```

## Configuration

Edit `config.yml`:

```yaml
# Window to capture (partial title match)
window_title: "Tales"

# Refresh rate in seconds
refresh_rate: 2.0

# OCR confidence threshold (0.0-1.0)
# Filters out garbage text by average per-line confidence
ocr_confidence: 0.6

# Subtitle appearance
font_size: 24
font_color: "#FFFFFF"
background_color: "#404040"
background_opacity: 0.8
```

## How It Works

1. **Screen Capture** - Captures the target window at the configured refresh rate
2. **OCR** - [MeikiOCR](https://github.com/rtr46/meikiocr) extracts Japanese text (optimized for pixel fonts)
3. **Translation** - [Sugoi V4](https://huggingface.co/entai2965/sugoi-v4-ja-en-ctranslate2) translates Japanese to English
4. **Display** - Shows translated text in a transparent floating overlay

## Controls

- **ESC** - Hide/show overlay
- **Q** - Quit
- Drag the overlay window to reposition

## Troubleshooting

### Window not found
Use `--list-windows` to see available windows. The window title is a partial match.

### Poor OCR accuracy
Try adjusting `ocr_confidence` in config. Lower values include more text (but may include garbage), higher values are stricter.

### Slow performance
First run downloads models (~1.5GB). Subsequent runs use cached models from `~/.cache/huggingface/`.
