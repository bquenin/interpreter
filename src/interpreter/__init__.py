"""Interpreter - Offline screen translator for Japanese retro games.

This application captures text from a target window, performs OCR using
MeikiOCR, translates using Sugoi V4, and displays subtitles in a
transparent overlay.
"""

import os

# Suppress harmless onnxruntime semaphore warning on exit
# Must be set before multiprocessing is imported
os.environ["PYTHONWARNINGS"] = "ignore::UserWarning:multiprocessing.resource_tracker"

# Suppress HuggingFace token warning (public models don't need auth)
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"

import argparse
import sys
import time

from .capture import WindowCapture
from .config import Config
from .ocr import OCR
from .overlay import SubtitleOverlay
from .translate import Translator, text_similarity

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
        "--debug",
        action="store_true",
        help="Show per-character OCR confidence scores"
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

    # Initialize components
    print("Initializing components...")

    # Initialize screen capture
    capture = WindowCapture(config.window_title)
    if not capture.find_window():
        print(f"Error: Window '{config.window_title}' not found.")
        print("Use --list-windows to see available windows.")
        sys.exit(1)
    print(f"  Window found: {config.window_title}")

    # Initialize OCR
    ocr = OCR(confidence_threshold=config.ocr_confidence, debug=args.debug)
    print("  OCR: MeikiOCR (will load on first use)")

    # Initialize translator (lazy loading)
    translator = None
    if not args.no_translate:
        translator = Translator()
        print("  Translator: Sugoi V4 (will load on first use)")
    else:
        print("  Translator: DISABLED (--no-translate)")

    # Initialize overlay (position on same display as target window)
    overlay = SubtitleOverlay(
        font_size=config.font_size,
        font_color=config.font_color,
        background_color=config.background_color,
        background_opacity=config.background_opacity,
    )
    display_bounds = capture.get_display_bounds()
    print(f"  Window bounds: {capture.bounds}")
    print(f"  Display bounds: {display_bounds}")
    overlay.create(target_bounds=display_bounds)
    print("  Overlay: Ready")

    print()
    print("Starting translation loop...")
    print("Press 'q' to quit, ESC to hide overlay")
    print("-" * 50)

    # Track previous text to avoid re-translating
    previous_text = ""
    last_capture_time = 0
    debug_mode = args.debug
    similarity_threshold = 0.9  # Skip if OCR is 90%+ similar to previous

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
            loop_start = time.perf_counter()

            # Capture window
            capture_start = time.perf_counter()
            image = capture.capture()
            capture_time = time.perf_counter() - capture_start

            if image is None:
                overlay.update_text("[Window not found]")
                continue

            # Extract text
            ocr_start = time.perf_counter()
            try:
                text = ocr.extract_text(image)
            except Exception as e:
                print(f"OCR error: {e}")
                continue
            ocr_time = time.perf_counter() - ocr_start

            # Skip if text hasn't changed (using fuzzy similarity to handle OCR jitter)
            similarity = text_similarity(text, previous_text)
            if similarity >= similarity_threshold:
                if debug_mode:
                    total_time = time.perf_counter() - loop_start
                    print(f"[TIMING] capture: {capture_time*1000:.0f}ms | ocr: {ocr_time*1000:.0f}ms | (similar: {similarity:.0%}) | total: {total_time*1000:.0f}ms")
                continue

            previous_text = text

            if not text:
                overlay.update_text("")
                if debug_mode:
                    total_time = time.perf_counter() - loop_start
                    print(f"[TIMING] capture: {capture_time*1000:.0f}ms | ocr: {ocr_time*1000:.0f}ms | (no text) | total: {total_time*1000:.0f}ms")
                continue

            # Translate (if enabled)
            translate_time = 0.0
            was_cached = False
            if translator:
                translate_start = time.perf_counter()
                try:
                    translated, was_cached = translator.translate(text)
                    display_text = translated
                except Exception as e:
                    print(f"Translation error: {e}")
                    display_text = f"[{text}]"  # Show original on error
                translate_time = time.perf_counter() - translate_start
            else:
                display_text = text  # Show OCR result without translation

            # Update overlay
            overlay.update_text(display_text)
            print(f"[OCR] {text}")
            if translator:
                cache_indicator = " (cached)" if was_cached else ""
                print(f"[EN]  {display_text}{cache_indicator}")

            # Print timing in debug mode
            if debug_mode:
                total_time = time.perf_counter() - loop_start
                cache_str = " CACHE" if was_cached else ""
                if translator:
                    print(f"[TIMING] capture: {capture_time*1000:.0f}ms | ocr: {ocr_time*1000:.0f}ms | translate: {translate_time*1000:.0f}ms{cache_str} | total: {total_time*1000:.0f}ms")
                else:
                    print(f"[TIMING] capture: {capture_time*1000:.0f}ms | ocr: {ocr_time*1000:.0f}ms | total: {total_time*1000:.0f}ms")
            print()

    except KeyboardInterrupt:
        print("\nInterrupted by user")
    finally:
        overlay.quit()
        print("Goodbye!")
