"""Main entry point for Interpreter.

This module is executed when running:
- python -m interpreter
- interpreter (via pyproject.toml entry point)
"""

import os
import sys

# Setup CUDA DLLs early (before any CUDA-dependent imports)
# This must happen before importing ctranslate2 or onnxruntime
if sys.platform == "win32":
    from .gpu import setup_cuda_dlls
    setup_cuda_dlls()

# Suppress harmless onnxruntime semaphore warning on exit
# Must be set before multiprocessing is imported
os.environ["PYTHONWARNINGS"] = "ignore::UserWarning:multiprocessing.resource_tracker"

# Suppress HuggingFace token warning (public models don't need auth)
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"

import argparse
import time
from typing import Optional

from pynput import keyboard

from .capture import WindowCapture
from .config import Config
from .ocr import OCR
from .overlay import Overlay
from .translate import Translator, text_similarity

# Main loop timing constants
TEXT_SIMILARITY_THRESHOLD = 0.9  # Skip OCR if 90%+ similar to previous
UI_POLL_INTERVAL = 0.05          # Sleep between UI updates (seconds)
PAUSED_POLL_INTERVAL = 0.1       # Sleep when overlay paused (seconds)


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


def _parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
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

    return parser.parse_args()


def _initialize_components(
    config: Config, args: argparse.Namespace
) -> tuple[WindowCapture, OCR, Optional[Translator], Overlay]:
    """Initialize capture, OCR, translator, and overlay.

    Args:
        config: Application configuration.
        args: Parsed command-line arguments.

    Returns:
        Tuple of (capture, ocr, translator, overlay).
    """
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

    print(f"  Window bounds: {capture.bounds}")

    # Start capture stream
    if not capture.start_stream():
        print("Error: Could not start capture stream.")
        sys.exit(1)
    print("  Capture stream started")

    # Wait for first frame for Retina scale detection
    initial_image = None
    for _ in range(50):  # Wait up to ~2.5 seconds
        initial_image = capture.get_frame()
        if initial_image is not None:
            break
        time.sleep(0.05)

    if initial_image is None:
        print("Error: Could not capture initial image for overlay setup.")
        capture.stop_stream()
        sys.exit(1)
    image_size = (initial_image.width, initial_image.height)

    # Debug: save initial capture to verify what we're capturing
    debug_path = "debug_capture.png"
    initial_image.save(debug_path)
    print(f"  Debug: saved capture to {debug_path}")

    # Create unified overlay
    display_bounds = capture.get_display_bounds()
    print(f"  Display bounds: {display_bounds}")

    overlay = Overlay(
        font_size=config.font_size,
        font_color=config.font_color,
        background_color=config.background_color,
    )
    overlay.create(
        display_bounds=display_bounds,
        window_bounds=capture.bounds,
        image_size=image_size,
        mode=config.overlay_mode,
    )
    print(f"  Overlay mode: {config.overlay_mode}")

    return capture, ocr, translator, overlay


def _create_hotkey_handler() -> tuple[dict, callable]:
    """Create hotkey state and handler function.

    Returns:
        Tuple of (state_dict, handler_function).
        state_dict contains flags that are set when hotkeys are pressed.
    """
    state = {
        "cycle_mode": False,
        "increase_font": False,
        "decrease_font": False,
        "quit": False,
    }

    def on_key_press(key):
        try:
            if hasattr(key, 'char'):
                if key.char == 'm':
                    state["cycle_mode"] = True
                elif key.char == '=':
                    state["increase_font"] = True
                elif key.char == '-':
                    state["decrease_font"] = True
                elif key.char == 'q':
                    state["quit"] = True
        except AttributeError:
            pass

    return state, on_key_press


def _run_main_loop(
    overlay: Overlay,
    capture: WindowCapture,
    ocr: OCR,
    translator: Optional[Translator],
    config: Config,
    hotkey_state: dict,
    debug_mode: bool,
) -> None:
    """Run the main translation loop.

    Args:
        overlay: The overlay window.
        capture: Window capture instance.
        ocr: OCR instance.
        translator: Translator instance (may be None).
        config: Application configuration.
        hotkey_state: Dict with hotkey flags.
        debug_mode: Whether to print debug info.
    """
    # Track previous text to avoid re-translating
    previous_text = ""
    last_capture_time = 0

    while overlay.is_running:
        # Process UI events
        overlay.update()

        # Handle global hotkeys
        if hotkey_state["cycle_mode"]:
            hotkey_state["cycle_mode"] = False
            # Cycle: off → banner → inplace → off
            if overlay.paused:
                overlay.set_mode("banner")
                overlay.resume()
                print("[MODE] Banner")
            elif overlay.mode == "banner":
                overlay.set_mode("inplace")
                print("[MODE] Inplace")
            else:
                overlay.pause()
                print("[MODE] Off")

        if hotkey_state["increase_font"]:
            hotkey_state["increase_font"] = False
            overlay.adjust_font_size(2)
            print(f"[FONT] Size: {overlay.font_size}")

        if hotkey_state["decrease_font"]:
            hotkey_state["decrease_font"] = False
            overlay.adjust_font_size(-2)
            print(f"[FONT] Size: {overlay.font_size}")

        if hotkey_state["quit"]:
            print("\n[QUIT] Exiting...")
            break

        # Skip processing if overlay is paused
        if overlay.paused:
            time.sleep(PAUSED_POLL_INTERVAL)
            continue

        # Check if it's time for a new capture
        current_time = time.time()
        if current_time - last_capture_time < config.refresh_rate:
            time.sleep(UI_POLL_INTERVAL)
            continue

        last_capture_time = current_time
        loop_start = time.perf_counter()

        # Get latest frame from stream
        capture_start = time.perf_counter()
        image = capture.get_frame()
        capture_time = time.perf_counter() - capture_start

        if image is None:
            if overlay.mode == "inplace":
                overlay.update_regions([])
            else:
                overlay.update_text("[Window not found]")
            continue

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
            if similarity >= TEXT_SIMILARITY_THRESHOLD:
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


def main():
    """Main entry point."""
    args = _parse_arguments()

    # List windows mode
    if args.list_windows:
        list_windows()
        return

    # Load configuration
    config = Config.load(args.config)

    # Override with CLI arguments
    if args.window:
        config.window_title = args.window
    if args.overlay_mode:
        config.overlay_mode = args.overlay_mode

    print("Interpreter - Offline Screen Translator")
    print("=" * 50)
    print(f"Target window: {config.window_title}")
    print(f"Refresh rate: {config.refresh_rate}s")
    print(f"Overlay mode: {config.overlay_mode}")
    print()

    # Initialize components
    capture, ocr, translator, overlay = _initialize_components(config, args)

    # Setup hotkeys
    hotkey_state, on_key_press = _create_hotkey_handler()
    keyboard_listener = keyboard.Listener(on_press=on_key_press)
    keyboard_listener.start()

    print()
    print("Starting translation loop...")
    print("Press 'm' to cycle mode (off → banner → inplace), '-/=' to adjust font, 'q' to quit")
    print("-" * 50)

    try:
        _run_main_loop(
            overlay, capture, ocr, translator,
            config, hotkey_state, args.debug
        )
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    finally:
        keyboard_listener.stop()
        capture.stop_stream()
        overlay.quit()
        print("Goodbye!")


if __name__ == "__main__":
    main()
