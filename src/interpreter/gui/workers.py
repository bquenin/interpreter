"""Background workers for OCR and translation."""

import hashlib
import threading
import time

import cv2

from PySide6.QtCore import QObject, Signal

from .. import log
from ..backends.base import Language, OCRBackend, TranslationBackend
from ..backends.ocr.meiki import MeikiOCRBackend
from ..backends.ocr.ocr_process import OCRProcess
from ..backends.ocr.paddleocr_backend import PaddleOCRBackend
from ..backends.translation.sugoi import SugoiTranslationBackend
from ..config import OverlayMode

logger = log.get_logger()


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


# Content detection for Linux/Wayland PipeWire captures
# PipeWire returns full-screen frames with window content in a corner
CONTENT_DARKNESS_THRESHOLD = 10  # RGB values below this are considered black/empty
MIN_CONTENT_SIZE = 50  # Minimum content size to avoid false positives


def detect_content_bounds(frame) -> tuple[int, int, int, int] | None:
    """Detect the bounding box of actual content in a frame.

    On Linux/Wayland with PipeWire, window captures return full-screen sized
    frames with the actual window content in a corner. This finds the region
    containing non-black pixels to crop to the actual content.

    Args:
        frame: numpy array (H, W, 4) in BGRA format.

    Returns:
        Tuple of (x, y, width, height) for content bounds, or None if no cropping needed.
    """
    import numpy as np

    h, w = frame.shape[:2]

    # Convert to grayscale (use green channel as approximation for speed)
    # BGRA format: index 1 is green
    gray = frame[:, :, 1]

    # Find pixels that are not black (above darkness threshold)
    mask = gray > CONTENT_DARKNESS_THRESHOLD

    # Find bounding box of non-black pixels
    coords = np.column_stack(np.where(mask))
    if len(coords) == 0:
        return None

    y_min, x_min = coords.min(axis=0)
    y_max, x_max = coords.max(axis=0)

    content_w = x_max - x_min + 1
    content_h = y_max - y_min + 1

    # Skip if content is too small (probably noise)
    if content_w < MIN_CONTENT_SIZE or content_h < MIN_CONTENT_SIZE:
        return None

    # Skip cropping if content fills most of the image (>90%)
    content_area = content_w * content_h
    total_area = w * h
    if content_area > 0.9 * total_area:
        return None

    logger.debug(
        "content bounds detected",
        original=f"{w}x{h}",
        content=f"{content_w}x{content_h}",
        offset=f"({x_min}, {y_min})",
    )

    return (x_min, y_min, content_w, content_h)


def compute_frame_hash(frame, thumb_size: int = 32) -> str:
    """Compute a hash of a frame for duplicate detection.

    Downsamples the frame to a small thumbnail before hashing to:
    - Make hashing fast
    - Be slightly tolerant to minor variations (compression artifacts, etc.)

    Args:
        frame: numpy array (H, W, 4) in BGRA format
        thumb_size: size to downsample to before hashing

    Returns:
        MD5 hash string of the downsampled frame
    """
    # Downsample to small thumbnail (fast and tolerant to minor changes)
    thumb = cv2.resize(frame, (thumb_size, thumb_size), interpolation=cv2.INTER_AREA)
    # Hash the thumbnail bytes
    return hashlib.md5(thumb.tobytes()).hexdigest()


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

    # Preview thumbnail ready (bytes, width, height)
    preview_ready = Signal(bytes, int, int)

    # Emitted when models are loaded and ready
    models_ready = Signal()

    # Emitted when model loading fails
    models_failed = Signal(str)

    # Per-model status signals: status can be "loading", "downloading", "ready", "error"
    ocr_status = Signal(str)
    translation_status = Signal(str)

    def __init__(
        self,
        ocr_backend: type[OCRBackend] | None = None,
        translation_backend: type[TranslationBackend] | None = None,
        load_ocr: bool = True,
        load_translation: bool = True,
        source_language: Language = Language.JAPANESE,
        crop_to_content: bool = False,
    ):
        """Initialize the process worker.

        Args:
            ocr_backend: OCR backend class to use. Defaults to MeikiOCRBackend.
            translation_backend: Translation backend class to use. Defaults to SugoiTranslationBackend.
            load_ocr: Whether to load the OCR model. Default True.
            load_translation: Whether to load the translation model. Default True.
            source_language: Source language for translation. Default Japanese.
            crop_to_content: Whether to auto-detect and crop to content bounds.
                           Used for Linux/Wayland PipeWire captures where the frame
                           is screen-sized but content is in a corner.
        """
        super().__init__()

        # Store backend classes (instantiated in worker thread)
        self._ocr_backend_class = ocr_backend or MeikiOCRBackend
        self._translation_backend_class = translation_backend or SugoiTranslationBackend

        # Flags for selective model loading
        self._load_ocr = load_ocr
        self._load_translation = load_translation

        # Source language for skipping non-matching text
        self._source_language = source_language

        # Content cropping for PipeWire captures
        self._crop_to_content = crop_to_content

        # Backend instances (created in worker thread)
        self._ocr: OCRBackend | None = None
        self._translator: TranslationBackend | None = None

        # Multiprocessing for PaddleOCR (holds GIL during inference)
        self._ocr_process: OCRProcess | None = None
        self._use_multiprocessing = False
        self._request_id = 0

        self._mode = OverlayMode.BANNER
        self._confidence_threshold = 0.6

        # Track which models failed (for "Fix Models" button)
        self._ocr_failed = False
        self._translation_failed = False

        # Threading
        self._frame_buffer = FrameBuffer()
        self._thread: threading.Thread | None = None

        # Frame hash cache - skip OCR if frame unchanged
        self._last_frame_hash: str | None = None
        self._last_ocr_text: str = ""
        self._last_translated_text: str = ""
        self._last_regions: list = []
        self._running = False

        # Translation cache for tracking cache hits (backends handle actual caching)
        self._last_translations: dict[str, str] = {}

    def set_backends(
        self,
        ocr_backend: type[OCRBackend] | None = None,
        translation_backend: type[TranslationBackend] | None = None,
    ):
        """Set the backend classes to use.

        Note: This should be called before start(). If called while running,
        the change will take effect on next start().

        Args:
            ocr_backend: OCR backend class to use.
            translation_backend: Translation backend class to use.
        """
        if ocr_backend is not None:
            self._ocr_backend_class = ocr_backend
        if translation_backend is not None:
            self._translation_backend_class = translation_backend

    def set_mode(self, mode: OverlayMode):
        """Set the overlay mode."""
        self._mode = mode

    def set_confidence_threshold(self, threshold: float):
        """Set the OCR confidence threshold."""
        self._confidence_threshold = threshold

    def set_source_language(self, language: Language):
        """Set the source language for text detection."""
        self._source_language = language

    def set_crop_to_content(self, enabled: bool):
        """Enable/disable auto-cropping to content bounds.

        Used for Linux/Wayland PipeWire captures where the frame is screen-sized
        but the actual window content is in a corner.
        """
        self._crop_to_content = enabled

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

        # Stop OCR process if using multiprocessing
        if self._ocr_process:
            self._ocr_process.stop()
            self._ocr_process = None

    def submit_frame(self, frame):
        """Send a frame for processing (non-blocking)."""
        if self._running:
            self._frame_buffer.put(frame)

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

    def _run(self):
        """Worker thread main loop."""
        logger.debug("worker thread starting")

        # Load OCR model (if requested)
        if self._load_ocr:
            self.ocr_status.emit("loading")
            try:
                # Check if this is PaddleOCR - use multiprocessing to avoid GIL issues
                # PaddlePaddle holds the GIL during inference, causing UI lag
                if issubclass(self._ocr_backend_class, PaddleOCRBackend):
                    logger.info("using multiprocessing for PaddleOCR")
                    self._use_multiprocessing = True
                    self._ocr_process = OCRProcess(
                        self._ocr_backend_class,
                        self._source_language,
                        self._confidence_threshold,
                    )
                    if not self._ocr_process.start():
                        raise RuntimeError("Failed to start OCR process")
                    self._ocr_failed = False
                else:
                    # Regular in-process OCR for other backends
                    self._use_multiprocessing = False
                    self._ocr = self._ocr_backend_class(confidence_threshold=self._confidence_threshold)
                    self._ocr.load()
                    self._ocr_failed = False
                self.ocr_status.emit("ready")
                logger.debug("OCR model loaded", backend=self._ocr_backend_class.__name__)
            except Exception as e:
                self._ocr_failed = True
                self.ocr_status.emit("error")
                logger.error("failed to load OCR model", error=str(e))

        # Load translation model (if requested)
        if self._load_translation:
            self.translation_status.emit("loading")
            try:
                self._translator = self._translation_backend_class()
                self._translator.load()
                self._translation_failed = False
                self.translation_status.emit("ready")
                logger.debug("translation model loaded", backend=self._translation_backend_class.__name__)
            except Exception as e:
                self._translation_failed = True
                self.translation_status.emit("error")
                logger.error("failed to load translation model", error=str(e))

        # Emit overall status based on what was requested to load
        ocr_ok = not self._load_ocr or not self._ocr_failed
        translation_ok = not self._load_translation or not self._translation_failed
        if ocr_ok and translation_ok:
            self.models_ready.emit()
        else:
            self.models_failed.emit("One or more models failed to load")

        # Only process frames if both models loaded successfully
        if not self._ocr_failed and not self._translation_failed:
            while self._running:
                frame = self._frame_buffer.get(timeout=0.5)
                if frame is not None:
                    self._process_frame(frame)

        logger.debug("worker thread stopped")

    def _process_frame(self, frame):
        """Process a frame through OCR and translation."""
        if not self._use_multiprocessing and self._ocr is None:
            return
        if self._use_multiprocessing and self._ocr_process is None:
            return

        frame_start = time.perf_counter()
        ocr_ms = 0
        translate_ms = 0
        was_cached = False

        # Generate preview thumbnail first (runs in worker thread, no GIL contention with main)
        self._generate_preview(frame)

        # Auto-detect and crop to content bounds (for PipeWire captures)
        if self._crop_to_content:
            bounds = detect_content_bounds(frame)
            if bounds is not None:
                x, y, w, h = bounds
                frame = frame[y : y + h, x : x + w]

        # Check if frame is identical to last one (skip OCR if unchanged)
        frame_hash = compute_frame_hash(frame)
        if frame_hash == self._last_frame_hash:
            # Frame unchanged - reuse cached results
            logger.debug("frame unchanged, skipping OCR")
            if self._mode == OverlayMode.INPLACE:
                self.regions_ready.emit(self._last_regions)
            else:
                self.text_ready.emit(self._last_translated_text)
            return

        # OCR - either via multiprocessing or direct
        try:
            ocr_start = time.perf_counter()
            mode = "regions" if self._mode == OverlayMode.INPLACE else "text"

            if self._use_multiprocessing:
                # Submit to OCR process and wait for result
                self._request_id += 1
                self._ocr_process.submit_frame(frame, self._request_id, mode)
                result = self._ocr_process.get_result(timeout=10.0)

                if result is None:
                    logger.warning("OCR timeout")
                    return

                ocr_result, req_id, result_ocr_ms = result

                # Check for error
                if isinstance(ocr_result, str) and ocr_result.startswith("error:"):
                    logger.error("OCR process error", error=ocr_result)
                    return

                if mode == "regions":
                    regions = ocr_result
                    text = " ".join(r.text for r in regions if r.text)
                else:
                    text = ocr_result
                    regions = []
                ocr_ms = result_ocr_ms
            else:
                # Direct backend call (for non-PaddleOCR backends)
                self._ocr.confidence_threshold = self._confidence_threshold
                if mode == "regions":
                    regions = self._ocr.extract_text_regions(frame)
                    text = " ".join(r.text for r in regions if r.text)
                else:
                    text = self._ocr.extract_text(frame)
                    regions = []
                ocr_ms = int((time.perf_counter() - ocr_start) * 1000)
        except Exception as e:
            logger.error("OCR error", error=str(e))
            return

        if not text:
            logger.debug("OCR returned no text", ocr_ms=ocr_ms)
            if self._mode == OverlayMode.INPLACE:
                self.regions_ready.emit([])
            else:
                self.text_ready.emit("")
            return

        # Skip translation for non-Japanese text when source is Japanese (banner mode)
        if self._source_language == Language.JAPANESE:
            if self._mode != OverlayMode.INPLACE and not contains_japanese(text):
                logger.debug("skipping translation - no Japanese characters detected")
                self.text_ready.emit("")
                return

        # Translation
        translate_start = time.perf_counter()
        if self._mode == OverlayMode.INPLACE:
            translated_regions = []
            all_cached = True
            for region in regions:
                if self._translator and region.text:
                    # Skip non-Japanese regions when source is Japanese
                    if self._source_language == Language.JAPANESE and not contains_japanese(region.text):
                        logger.debug(
                            "skipping region - no Japanese characters",
                            text=region.text,
                        )
                        continue
                    try:
                        # Check our local cache first
                        cached = region.text in self._last_translations
                        if cached:
                            translated = self._last_translations[region.text]
                        else:
                            translated = self._translator.translate(region.text)
                            self._last_translations[region.text] = translated
                            all_cached = False
                        logger.debug("region translated", ocr=region.text, translated=translated)
                    except Exception as e:
                        logger.warning("Translation error", error=str(e), text=region.text)
                        translated = region.text
                        all_cached = False
                else:
                    continue
                translated_regions.append((translated, region.bbox))
            translate_ms = int((time.perf_counter() - translate_start) * 1000)
            was_cached = all_cached and len(translated_regions) > 0

            # Cache for frame hash comparison
            self._last_regions = translated_regions
            self._last_frame_hash = frame_hash

            self.regions_ready.emit(translated_regions)
        else:
            logger.debug("OCR text", text=text or "")
            if self._translator:
                try:
                    # Skip translation for very short text to avoid hallucinations
                    # (e.g., single letter "C" -> "Annex C of EU regulation...")
                    if len(text.strip()) < 3:
                        logger.debug("text too short for translation", length=len(text.strip()))
                        translated = text
                        was_cached = True  # Treat as cached to avoid logging
                    # Check our local cache first
                    elif text in self._last_translations:
                        translated = self._last_translations[text]
                        was_cached = True
                    else:
                        translated = self._translator.translate(text)
                        self._last_translations[text] = translated
                        was_cached = False
                    logger.debug("translated text", translated=translated or "")
                except Exception as e:
                    logger.warning("Translation error", error=str(e), text=text)
                    translated = f"[{text}]"
            else:
                translated = text
            translate_ms = int((time.perf_counter() - translate_start) * 1000)

            # Cache for frame hash comparison
            self._last_ocr_text = text
            self._last_translated_text = translated
            self._last_frame_hash = frame_hash

            self.text_ready.emit(translated)

        total_ms = int((time.perf_counter() - frame_start) * 1000)
        translate_str = f"{translate_ms} (cached)" if was_cached else str(translate_ms)
        logger.debug(
            "frame processed",
            ocr_ms=ocr_ms,
            translate_ms=translate_str,
            total_ms=total_ms,
        )

        # Limit cache size
        if len(self._last_translations) > 200:
            # Remove oldest entries
            keys = list(self._last_translations.keys())
            for key in keys[:100]:
                del self._last_translations[key]

    def _generate_preview(self, frame):
        """Generate preview thumbnail and emit to main thread.

        Runs in worker thread to avoid GIL contention with main thread.
        """
        import cv2

        preview_start = time.perf_counter()

        h, w = frame.shape[:2]
        max_w, max_h = 320, 240

        # Calculate scale to fit within max_size while preserving aspect ratio
        scale = min(max_w / w, max_h / h)
        if scale < 1.0:
            new_w = int(w * scale)
            new_h = int(h * scale)
            # Resize with cv2 (fast) - use INTER_AREA for downscaling
            frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)

        # Convert BGRA to RGB
        rgb = frame[:, :, [2, 1, 0]]

        # Get dimensions and raw bytes
        h, w = rgb.shape[:2]
        data = rgb.tobytes()

        preview_ms = int((time.perf_counter() - preview_start) * 1000)
        logger.debug("preview generated", width=w, height=h, preview_ms=preview_ms)

        # Emit to main thread
        self.preview_ready.emit(data, w, h)
