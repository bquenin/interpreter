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
- **Multi-display support** - Overlay appears on the same display as the game

## Requirements

- **Windows 10 version 1903+**, macOS, or Linux (X11/XWayland/Wayland)
- At least 6 GB of free disk space for application dependencies and first-run model downloads

### Linux Notes

- **Global hotkeys** require `input` group membership. The installer will show instructions.
- **Native Wayland capture** requires GStreamer PipeWire plugin. The installer will attempt to install it automatically.
- **Inplace overlay** on Wayland only works with fullscreen windows (Wayland's security model prevents knowing window positions).
- **Qt platform plugin** (`xcb`) requires `libxcb-cursor0` (Debian/Ubuntu/Mint) or `xcb-util-cursor` (Fedora/Arch). Without it the GUI will abort with `Could not load the Qt platform plugin "xcb"`.

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

To update to the latest version, run the installer again (see Installation above).

## Uninstalling

**macOS/Linux:**
```bash
curl -LsSf https://raw.githubusercontent.com/bquenin/interpreter/main/uninstall.sh | bash
```

**Windows (PowerShell):**
```powershell
powershell -c "irm https://raw.githubusercontent.com/bquenin/interpreter/main/uninstall.ps1 | iex"
```

This removes interpreter-v2, config files, and cached models.

## Usage

```bash
interpreter-v2
```

This opens the GUI where you can select a window to capture and configure all settings.

## Overlay Modes

### Banner Mode (default)
A subtitle bar at the bottom of the screen displaying translated text. Draggable, opaque background, centered text.

### Inplace Mode
Transparent overlay positioned over the game window. Translated text appears directly over the original Japanese text at OCR-detected positions. Click-through so you can interact with the game.

## How It Works

1. **Screen Capture** - Captures the target window at the configured refresh rate
2. **OCR** - [MeikiOCR](https://github.com/rtr46/meikiocr) extracts Japanese text (optimized for pixel fonts)
3. **Translation** - [Sugoi V4](https://huggingface.co/entai2965/sugoi-v4-ja-en-ctranslate2) translates Japanese to English
4. **Display** - Shows translated text in the selected overlay mode

## Using a Different Translation Model (Ollama / OpenAI-compatible)

Sugoi V4 is the built-in default and needs no setup. If you want to try a larger language model, the **Translation** panel in the main window can send text to an [Ollama](https://ollama.com) server or to any OpenAI-compatible endpoint (LM Studio, llama.cpp server, vLLM, OpenRouter, OpenAI, ...). You bring the model; Interpreter only sends the OCR text and shows the reply.

### Quick start with Ollama

1. Install Ollama and pull a model. A 4B-class model is the practical minimum for Japanese; anything under 2B mostly outputs romaji or nonsense.
   ```bash
   ollama pull gemma3:4b
   ```
2. In Interpreter, set **Engine** to *LLM endpoint*, keep the provider on *Ollama* and the URL on `http://127.0.0.1:11434`, click **Refresh** and pick the model.
3. Click **Test**. It translates a sample line and shows the round-trip time. Then click **Apply**; the translation engine reloads without interrupting capture.

Use `127.0.0.1`, not `localhost`: on Windows, `localhost` adds about two seconds to every request.

### What to expect

- **Speed**: on an RTX 4070 Ti, `gemma3:4b` answers in about 100 ms per line. Larger models and CPU-only machines take seconds per line, which is fine for dialogue and painful for menus. The fuzzy translation cache still avoids re-translating text that has not changed.
- **Quality**: larger models keep names and tone more consistent, and the previous few lines are sent as context. They also know many games and may use the official localized names instead of a literal translation. Edit the **Prompt** if you want different behaviour.
- **Reasoning models** (Qwen3 and friends): thinking is turned off automatically on Ollama. On other servers, inline `<think>` blocks are stripped from the reply.
- **Target language**: the LLM engine can translate into any language the model handles. OCR is still Japanese only.
- **Remote endpoints**: the API key is stored in plain text in `config.yml`, every line of game text leaves your machine, and each request may cost money. Nothing is sent anywhere unless you pick the LLM engine.

The same settings live in `config.yml` under `translation_backend` and `llm` if you prefer editing them by hand.

## Troubleshooting

### Poor OCR accuracy
Try adjusting the OCR confidence slider in the GUI. Lower values include more text (but may include garbage), higher values are stricter.

### Slow performance
First run downloads models (~1.5GB). Subsequent runs use cached models from `~/.cache/huggingface/`.
