"""Background workers for OCR and translation."""

import threading
import time

from PySide6.QtCore import QObject, Signal

from .. import log
from ..config import Config, OverlayMode
from ..ocr import OCREngine, create_ocr
from ..translate import TranslationEngine, create_translator

logger = log.get_logger()

# After this many consecutive runtime failures an engine is marked as failed
# (status "Error" + Fix Models) instead of retrying on every frame forever.
MAX_CONSECUTIVE_TRANSLATION_FAILURES = 3
MAX_CONSECUTIVE_OCR_FAILURES = 3


def contains_japanese(text: str) -> bool:
    """Check if text contains Japanese characters."""
    for char in text:
        code = ord(char)
        # Hiragana: U+3040-U+309F
        # Katakana: U+30A0-U+30FF
        # CJK (Kanji): U+4E00-U+9FFF
        # Half-width Katakana: U+FF65-U+FF9F
        if (
            0x3040 <= code <= 0x309F  # Hiragana
            or 0x30A0 <= code <= 0x30FF  # Katakana
            or 0x4E00 <= code <= 0x9FFF  # Kanji
            or 0xFF65 <= code <= 0xFF9F  # Half-width Katakana
        ):
            return True
    return False


class FrameBuffer:
    """Thread-safe 'latest frame' buffer with signaling."""

    def __init__(self):
        self._frame = None
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._closed = False

    def put(self, frame):
        """Store new frame and signal worker."""
        with self._condition:
            self._frame = frame
            self._condition.notify()

    def get(self, timeout=None):
        """Wait for and retrieve frame. Returns None on timeout or close."""
        with self._condition:
            if self._condition.wait_for(lambda: self._frame is not None or self._closed, timeout):
                if self._closed:
                    return None
                frame = self._frame
                self._frame = None
                return frame
            return None

    def close(self):
        """Signal worker to stop waiting."""
        with self._condition:
            self._closed = True
            self._condition.notify()


class ProcessWorker(QObject):
    """Worker for OCR and translation processing.

    Uses Python threading (not QThread) to avoid conflicts between
    ONNX runtime and windows-capture on Windows.

    Frames are sent via FrameBuffer, results emitted via Qt signals.
    """

    # Banner mode: single translated text
    text_ready = Signal(str)

    # Inplace mode: list of (text, bbox) regions
    regions_ready = Signal(list)

    # Raw OCR results (list of OCRResult) - emitted before translation for visualization
    ocr_results_ready = Signal(list)

    # Emitted when models are loaded and ready
    models_ready = Signal()

    # Emitted when model loading fails, with a user-readable description
    models_failed = Signal(str)

    # Per-model status signals: status can be "loading", "downloading", "ready", "error"
    ocr_status = Signal(str)
    translation_status = Signal(str)

    def __init__(self, config: Config):
        super().__init__()
        self._config = config
        self._ocr: OCREngine | None = None
        self._translator: TranslationEngine | None = None
        self._mode = OverlayMode.BANNER
        self._confidence_threshold = 0.6

        # Track which models failed (for "Fix Models" button) and why
        self._ocr_failed = False
        self._translation_failed = False
        self._ocr_error = ""
        self._translation_error = ""
        # Consecutive runtime failures since the last success
        self._ocr_failures = 0
        self._translation_failures = 0

        # Set when the UI changes a backend; handled on the worker thread
        self._reload_ocr = False
        self._reload_translation = False

        # Threading
        self._frame_buffer = FrameBuffer()
        self._thread: threading.Thread | None = None
        self._running = False

    def set_mode(self, mode: OverlayMode):
        """Set the overlay mode."""
        self._mode = mode

    def set_confidence_threshold(self, threshold: float):
        """Set the OCR confidence threshold."""
        self._confidence_threshold = threshold

    def start(self, ocr_confidence: float):
        """Start the worker thread and load models."""
        if self._thread is not None:
            return

        self._confidence_threshold = ocr_confidence
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the worker thread."""
        self._running = False
        self._frame_buffer.close()
        self._thread = None

    def submit_frame(self, frame):
        """Send a frame for processing (non-blocking)."""
        if self._running:
            self._frame_buffer.put(frame)

    def reload_ocr(self):
        """Rebuild the OCR engine from the current config (after a settings change).

        Runs on the worker thread between frames, so the translation engine stays
        loaded and capture is not interrupted.
        """
        self._reload_ocr = True  # picked up within the loop's 0.5 s poll interval

    def reload_translation(self):
        """Rebuild the translation engine from the current config (after a settings change).

        Runs on the worker thread between frames, so OCR keeps its loaded model and
        capture is not interrupted.
        """
        self._reload_translation = True  # picked up within the loop's 0.5 s poll interval

    def has_failed_models(self) -> bool:
        """Check if any models failed to load."""
        return self._ocr_failed or self._translation_failed

    def get_failed_models(self) -> list[str]:
        """Get list of model types that failed to load."""
        failed = []
        if self._ocr_failed:
            failed.append("ocr")
        if self._translation_failed:
            failed.append("translation")
        return failed

    def get_failure_message(self) -> str:
        """Describe why loading failed, for the status bar."""
        return "; ".join(m for m in (self._ocr_error, self._translation_error) if m)

    def _run(self):
        """Worker thread main loop."""
        logger.debug("worker thread starting")

        self._load_ocr()
        self._load_translator()
        self._emit_models_status()

        while self._running:
            if self._reload_ocr:
                self._reload_ocr = False
                self._load_ocr()
                self._emit_models_status()
            if self._reload_translation:
                self._reload_translation = False
                self._load_translator()
                self._emit_models_status()

            frame = self._frame_buffer.get(timeout=0.5)
            # Only process frames if both models loaded successfully
            if frame is not None and not (self._ocr_failed or self._translation_failed):
                self._process_frame(frame)

        self._discard_ocr()
        logger.debug("worker thread stopped")

    def _discard_ocr(self):
        """Drop the current OCR engine, releasing any connection it holds."""
        ocr, self._ocr = self._ocr, None
        close = getattr(ocr, "close", None)
        if callable(close):
            close()

    def _load_ocr(self):
        """Build and load the configured OCR engine, recording failure for the Fix Models flow."""
        self.ocr_status.emit("loading")
        self._discard_ocr()
        try:
            ocr = create_ocr(self._config)
            ocr.confidence_threshold = self._confidence_threshold
            ocr.load()
            self._ocr = ocr
            self._ocr_failed = False
            self._ocr_error = ""
            self._ocr_failures = 0
            self.ocr_status.emit("ready")
            logger.debug("OCR engine loaded", engine=ocr.name)
        except Exception as e:
            self._ocr_failed = True
            self._ocr_error = str(e)
            self.ocr_status.emit("error")
            logger.error("failed to load OCR engine", error=str(e))

    def _load_translator(self):
        """Build and load the configured translation engine."""
        self.translation_status.emit("loading")
        self._translator = None
        try:
            translator = create_translator(self._config)
            translator.load()
            self._translator = translator
            self._translation_failed = False
            self._translation_error = ""
            self._translation_failures = 0
            self.translation_status.emit("ready")
            logger.debug("translation engine loaded", engine=translator.name)
        except Exception as e:
            self._translation_failed = True
            self._translation_error = str(e)
            self.translation_status.emit("error")
            logger.error("failed to load translation engine", error=str(e))

    def _record_ocr_failure(self, error: Exception) -> bool:
        """Count a runtime OCR failure; mark the engine failed after repeated ones.

        Only the owocr backend fails at runtime (server stopped or paused). Once
        marked failed, frames are skipped until the UI reloads the engine.

        Returns:
            True if the engine has just been marked as failed.
        """
        self._ocr_failures += 1
        if self._ocr_failures < MAX_CONSECUTIVE_OCR_FAILURES:
            return False
        self._ocr_failed = True
        self._ocr_error = str(error)
        self.ocr_status.emit("error")
        self.models_failed.emit(self._ocr_error)
        logger.error("OCR engine marked as failed", failures=self._ocr_failures, error=self._ocr_error)
        return True

    def _record_translation_failure(self, error: Exception) -> bool:
        """Count a runtime translation failure; mark the engine failed after repeated ones.

        A dead endpoint would otherwise keep showing "Ready" while every frame fails.
        Once marked failed, frames are skipped until the UI reloads the engine
        (Apply or Fix Models), which is the recovery path.

        Returns:
            True if the engine has just been marked as failed.
        """
        self._translation_failures += 1
        if self._translation_failures < MAX_CONSECUTIVE_TRANSLATION_FAILURES:
            return False
        self._translation_failed = True
        self._translation_error = str(error)
        self.translation_status.emit("error")
        self.models_failed.emit(self._translation_error)
        logger.error(
            "translation engine marked as failed",
            failures=self._translation_failures,
            error=self._translation_error,
        )
        return True

    def _emit_models_status(self):
        if self._ocr_failed or self._translation_failed:
            self.models_failed.emit(self.get_failure_message() or "One or more models failed to load")
        else:
            self.models_ready.emit()

    def _process_frame(self, frame):
        """Process a frame through OCR and translation."""
        if self._ocr is None:
            return

        frame_start = time.perf_counter()
        ocr_ms = 0
        translate_ms = 0
        was_cached = False

        # Update OCR threshold
        self._ocr.confidence_threshold = self._confidence_threshold

        # OCR - always extract regions to get bboxes for visualization
        try:
            ocr_start = time.perf_counter()
            regions = self._ocr.extract_text_regions(frame)
            text = " ".join(r.text for r in regions if r.text)
            ocr_ms = int((time.perf_counter() - ocr_start) * 1000)
            self._ocr_failures = 0
        except Exception as e:
            logger.error("OCR error", error=str(e))
            self._record_ocr_failure(e)
            return

        # Emit raw OCR results for visualization (e.g., OCR config dialog)
        self.ocr_results_ready.emit(regions)

        if not text:
            if self._mode == OverlayMode.INPLACE:
                self.regions_ready.emit([])
            else:
                self.text_ready.emit("")
            return

        # Skip translation for non-Japanese text
        if not contains_japanese(text):
            logger.debug("skipping translation - no Japanese characters detected")
            if self._mode == OverlayMode.INPLACE:
                self.regions_ready.emit([])
            else:
                self.text_ready.emit("")
            return

        # Translation
        translate_start = time.perf_counter()
        if self._mode == OverlayMode.INPLACE:
            translated_regions = []
            all_cached = True
            for region in regions:
                if self._translator and region.text:
                    # Skip non-Japanese regions
                    if not contains_japanese(region.text):
                        logger.debug(
                            "skipping region - no Japanese characters",
                            text=region.text[:30],
                        )
                        continue
                    try:
                        translated, cached = self._translator.translate(region.text)
                        if not cached:
                            all_cached = False
                        self._translation_failures = 0
                    except Exception as e:
                        logger.warning("Translation error", error=str(e), text=region.text[:50])
                        translated = region.text
                        all_cached = False
                        if self._record_translation_failure(e):
                            break
                else:
                    continue
                translated_regions.append((translated, region.bbox))
            translate_ms = int((time.perf_counter() - translate_start) * 1000)
            was_cached = all_cached and len(translated_regions) > 0

            self.regions_ready.emit(translated_regions)
        else:
            if self._translator:
                try:
                    translated, was_cached = self._translator.translate(text)
                    self._translation_failures = 0
                except Exception as e:
                    logger.warning("Translation error", error=str(e), text=text[:50])
                    translated = f"[{text}]"
                    self._record_translation_failure(e)
            else:
                translated = text
            translate_ms = int((time.perf_counter() - translate_start) * 1000)

            self.text_ready.emit(translated)

        total_ms = int((time.perf_counter() - frame_start) * 1000)
        translate_str = f"{translate_ms} (cached)" if was_cached else str(translate_ms)
        logger.debug(
            "frame processed",
            ocr_ms=ocr_ms,
            translate_ms=translate_str,
            total_ms=total_ms,
        )
