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
import threading

from pynput import keyboard

from .capture import WindowCapture
from .config import Config
from .ocr import OCR
from .overlay import Overlay
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
    parser.add_argument(
        "--overlay-mode", "-m",
        type=str,
        choices=["banner", "inplace"],
        default=None,
        help="Overlay mode: banner (subtitle at bottom) or inplace (over game text)"
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

    # Override overlay mode if specified
    if args.overlay_mode:
        config.overlay_mode = args.overlay_mode

    print("Interpreter - Offline Screen Translator")
    print("=" * 50)
    print(f"Target window: {config.window_title}")
    print(f"Refresh rate: {config.refresh_rate}s")
    print(f"Overlay mode: {config.overlay_mode}")
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

    # Initialize both overlays (for hot-switching)
    print(f"  Window bounds: {capture.bounds}")

    # Initial capture for Retina scale detection
    initial_image = capture.capture()
    if initial_image is None:
        print("Error: Could not capture initial image for overlay setup.")
        sys.exit(1)
    image_size = (initial_image.width, initial_image.height)

    # Create unified overlay
    display_bounds = capture.get_display_bounds()
    print(f"  Display bounds: {display_bounds}")

    overlay = Overlay(
        font_size=config.font_size,
        font_color=config.font_color,
        background_color=config.background_color,
        background_opacity=config.background_opacity,
    )
    overlay.create(
        display_bounds=display_bounds,
        window_bounds=capture.bounds,
        image_size=image_size,
        mode=config.overlay_mode,
    )
    print(f"  Overlay mode: {config.overlay_mode}")

    # Shared state for hotkey handling
    should_cycle_mode = False
    should_increase_font = False
    should_decrease_font = False

    def on_key_press(key):
        """Handle global key presses."""
        nonlocal should_cycle_mode, should_increase_font, should_decrease_font
        try:
            if hasattr(key, 'char'):
                if key.char == 'm':
                    should_cycle_mode = True
                elif key.char == '=':
                    should_increase_font = True
                elif key.char == '-':
                    should_decrease_font = True
        except AttributeError:
            pass

    # Start global keyboard listener in background thread
    keyboard_listener = keyboard.Listener(on_press=on_key_press)
    keyboard_listener.start()

    print()
    print("Starting translation loop...")
    print("Press 'm' to cycle mode (off → banner → inplace), '-/=' to adjust font, Ctrl+C to quit")
    print("-" * 50)

    # Track previous text to avoid re-translating
    previous_text = ""
    previous_display_text = ""  # Last translated text (for banner mode)
    previous_regions = []  # Last translated regions (for inplace mode)
    last_capture_time = 0
    debug_mode = args.debug
    debug_save_done = False
    similarity_threshold = 0.9  # Skip if OCR is 90%+ similar to previous

    try:
        while overlay.is_running:
            # Process UI events
            overlay.update()

            # Handle global hotkeys
            if should_cycle_mode:
                should_cycle_mode = False
                # Cycle: off → banner → inplace → off
                if overlay.paused:
                    # Off → Banner
                    overlay.set_mode("banner")
                    overlay.resume()
                    print("[MODE] Banner")
                elif overlay.mode == "banner":
                    # Banner → Inplace
                    overlay.set_mode("inplace")
                    print("[MODE] Inplace")
                else:
                    # Inplace → Off
                    overlay.pause()
                    print("[MODE] Off")

            if should_increase_font:
                should_increase_font = False
                overlay.adjust_font_size(2)
                print(f"[FONT] Size: {overlay.font_size}")

            if should_decrease_font:
                should_decrease_font = False
                overlay.adjust_font_size(-2)
                print(f"[FONT] Size: {overlay.font_size}")

            # Skip processing if overlay is paused
            if overlay.paused:
                time.sleep(0.1)
                continue

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
                if overlay.mode == "inplace":
                    overlay.update_regions([])  # Hide inplace overlay
                else:
                    overlay.update_text("[Window not found]")
                continue

            # Debug: show captured image dimensions and save first image
            if debug_mode:
                if not debug_save_done:
                    print(f"[DBG] Captured image size: {image.width}x{image.height}")
                    print(f"[DBG] Window bounds: {capture.bounds}")
                    image.save("/tmp/interpreter_debug_capture.png")
                    print(f"[DBG] Saved capture to /tmp/interpreter_debug_capture.png")
                    debug_save_done = True

            # Update overlay position if game window moved/resized
            overlay.update_position(
                capture.bounds,
                display_bounds=capture.get_display_bounds(),
                image_size=(image.width, image.height)
            )

            # Extract text
            ocr_start = time.perf_counter()
            try:
                if overlay.mode == "inplace":
                    # Get multiple text regions for inplace mode
                    regions = ocr.extract_text_regions(image)
                    text = " ".join(r.text for r in regions if r.text)
                else:
                    text = ocr.extract_text(image)
                    regions = []
            except Exception as e:
                print(f"OCR error: {e}")
                continue
            ocr_time = time.perf_counter() - ocr_start

            # Skip if text hasn't changed (banner mode only - inplace always updates)
            if overlay.mode != "inplace":
                similarity = text_similarity(text, previous_text)
                if similarity >= similarity_threshold:
                    if debug_mode:
                        total_time = time.perf_counter() - loop_start
                        print(f"[TIMING] capture: {capture_time*1000:.0f}ms | ocr: {ocr_time*1000:.0f}ms | (similar: {similarity:.0%}) | total: {total_time*1000:.0f}ms")
                    continue
                previous_text = text

            if not text:
                if overlay.mode == "inplace":
                    overlay.update_regions([])
                else:
                    overlay.update_text("")
                if debug_mode:
                    total_time = time.perf_counter() - loop_start
                    print(f"[TIMING] capture: {capture_time*1000:.0f}ms | ocr: {ocr_time*1000:.0f}ms | (no text) | total: {total_time*1000:.0f}ms")
                continue

            if overlay.mode == "inplace" and debug_mode:
                print(f"[DBG] Found {len(regions)} regions")

            # Translate
            translate_time = 0.0
            was_cached = False
            if overlay.mode == "inplace":
                # Translate each region separately
                translated_regions = []
                translate_start = time.perf_counter()
                for region in regions:
                    if translator:
                        try:
                            translated, cached = translator.translate(region.text)
                            was_cached = was_cached or cached
                        except Exception as e:
                            print(f"Translation error: {e}")
                            translated = region.text
                    else:
                        translated = region.text
                    translated_regions.append((translated, region.bbox))
                translate_time = time.perf_counter() - translate_start

                # Remember for next iteration
                previous_regions = translated_regions
                previous_display_text = " ".join(t for t, _ in translated_regions)

                # Update overlay with all regions
                overlay.update_regions(translated_regions)

                # Print each region
                for region, (translated, _) in zip(regions, translated_regions):
                    print(f"[OCR] {region.text}")
                    if translator:
                        print(f"[EN]  {translated}")
            else:
                # Banner mode: single text block
                if translator:
                    translate_start = time.perf_counter()
                    try:
                        translated, was_cached = translator.translate(text)
                        display_text = translated
                    except Exception as e:
                        print(f"Translation error: {e}")
                        display_text = f"[{text}]"
                    translate_time = time.perf_counter() - translate_start
                else:
                    display_text = text

                previous_display_text = display_text
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
        keyboard_listener.stop()
        overlay.quit()
        print("Goodbye!")
