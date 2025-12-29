"""Interpreter - Offline screen translator for Japanese retro games.

This application captures text from a target window, performs OCR using
MeikiOCR, translates using Sugoi V4, and displays subtitles in a
transparent overlay.
"""

import argparse
import sys
import time
from pathlib import Path

from .capture import WindowCapture
from .config import Config
from .ocr import OCR
from .overlay import SubtitleOverlay
from .translate import Translator

__version__ = "0.1.0"


def list_windows():
    """List all available windows and exit."""
    print("Available windows:")
    print("-" * 60)

    windows = WindowCapture.list_windows()
    for w in windows:
        title = w["title"][:50] + "..." if len(w["title"]) > 50 else w["title"]
        print(f"  {title}")

    print("-" * 60)
    print(f"Total: {len(windows)} windows")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Offline screen translator for Japanese games"
    )
    parser.add_argument(
        "--config", "-c",
        type=str,
        default=None,
        help="Path to config file (default: config.yml)"
    )
    parser.add_argument(
        "--window", "-w",
        type=str,
        default=None,
        help="Window title to capture (overrides config)"
    )
    parser.add_argument(
        "--list-windows", "-l",
        action="store_true",
        help="List available windows and exit"
    )
    parser.add_argument(
        "--no-translate",
        action="store_true",
        help="Skip translation (OCR only, for testing)"
    )
    parser.add_argument(
        "--models-dir",
        type=str,
        default=None,
        help="Path to models directory (default: ~/.interpreter/models)"
    )

    args = parser.parse_args()

    # List windows mode
    if args.list_windows:
        list_windows()
        return

    # Load configuration
    config = Config.load(args.config)

    # Override window title if specified
    if args.window:
        config.window_title = args.window

    print("Interpreter - Offline Screen Translator")
    print("=" * 50)
    print(f"Target window: {config.window_title}")
    print(f"Refresh rate: {config.refresh_rate}s")
    print()

    # Set up models directory
    models_dir = Path(args.models_dir) if args.models_dir else None

    # Initialize components
    print("Initializing components...")

    # Initialize screen capture
    capture = WindowCapture(config.window_title)
    if not capture.find_window():
        print(f"Error: Window '{config.window_title}' not found.")
        print("Use --list-windows to see available windows.")
        sys.exit(1)
    print(f"  Window found: {config.window_title}")

    # Initialize OCR with confidence threshold from config
    ocr = OCR(confidence_threshold=config.confidence_threshold)
    print("  OCR: MeikiOCR (will load on first use)")

    # Initialize translator (lazy loading)
    translator = None
    if not args.no_translate:
        # Get model path if models_dir specified
        model_path = None
        if models_dir:
            model_path = models_dir / "sugoi-v4-ja-en-ct2"

        translator = Translator(model_path=model_path)
        print("  Translator: Sugoi V4 (will load on first use)")
    else:
        print("  Translator: DISABLED (--no-translate)")

    # Initialize overlay
    overlay = SubtitleOverlay(
        font_size=config.font_size,
        font_color=config.font_color,
        background_color=config.background_color,
        background_opacity=config.background_opacity,
    )
    overlay.create()
    print("  Overlay: Ready")

    print()
    print("Starting translation loop...")
    print("Press 'q' to quit, ESC to hide overlay")
    print("-" * 50)

    # Track previous text to avoid re-translating
    previous_text = ""
    last_capture_time = 0

    try:
        while overlay.is_running:
            # Process UI events
            overlay.update()

            # Check if it's time for a new capture
            current_time = time.time()
            if current_time - last_capture_time < config.refresh_rate:
                time.sleep(0.05)  # Small sleep to prevent busy loop
                continue

            last_capture_time = current_time

            # Capture window
            image = capture.capture()
            if image is None:
                overlay.update_text("[Window not found]")
                continue

            # Extract text
            try:
                text = ocr.extract_text(image)
            except Exception as e:
                print(f"OCR error: {e}")
                continue

            # Skip if text hasn't changed
            if text == previous_text:
                continue

            previous_text = text

            if not text:
                overlay.update_text("")
                continue

            # Translate (if enabled)
            if translator:
                try:
                    translated = translator.translate(text)
                    display_text = translated
                except Exception as e:
                    print(f"Translation error: {e}")
                    display_text = f"[{text}]"  # Show original on error
            else:
                display_text = text  # Show OCR result without translation

            # Update overlay
            overlay.update_text(display_text)
            print(f"[OCR] {text}")
            if translator:
                print(f"[EN]  {display_text}")
            print()

    except KeyboardInterrupt:
        print("\nInterrupted by user")
    finally:
        overlay.quit()
        print("Goodbye!")
