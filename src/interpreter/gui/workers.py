"""Background workers for OCR and translation."""

import time

from PySide6.QtCore import QObject, Signal, Slot

from .. import log
from ..ocr import OCR
from ..translate import Translator

logger = log.get_logger()


class ProcessWorker(QObject):
    """Worker for OCR and translation processing.

    Processes frames through OCR and translation pipeline.
    Emits result signals for banner or inplace mode.

    This worker is designed to be moved to a QThread using moveToThread().
    Call initialize_models() after moving to the thread to load models
    on the worker thread.
    """

    # Banner mode: single translated text
    text_ready = Signal(str)  # translated text

    # Inplace mode: list of (text, bbox) regions
    regions_ready = Signal(list)  # list of (translated_text, bbox)

    # Emitted when models are loaded and ready
    models_ready = Signal()

    # Emitted when model loading fails
    models_failed = Signal(str)  # error message

    def __init__(self):
        super().__init__()
        self._ocr: OCR | None = None
        self._translator: Translator | None = None
        self._mode = "banner"
        self._processing = False  # Prevent queue buildup

    def set_mode(self, mode: str):
        """Set the overlay mode (banner or inplace)."""
        self._mode = mode

    @Slot(float)
    def initialize_models(self, ocr_confidence: float):
        """Initialize OCR and translation models on the worker thread.

        This must be called after moveToThread() to ensure models
        are owned by the worker thread.

        Args:
            ocr_confidence: Initial OCR confidence threshold
        """
        logger.debug("initializing models on worker thread")
        try:
            self._ocr = OCR(confidence_threshold=ocr_confidence)
            self._ocr.load()
            logger.debug("OCR model loaded")

            self._translator = Translator()
            self._translator.load()
            logger.debug("translation model loaded")

            self.models_ready.emit()
        except Exception as e:
            logger.error("failed to initialize models", error=str(e))
            self.models_failed.emit(str(e))

    @Slot(object, float)
    def process_frame_slot(self, frame, confidence_threshold: float = 0.6):
        """Process a frame through OCR and translation (slot for cross-thread calls).

        This slot is designed to be called via QMetaObject.invokeMethod() from
        the main thread. It will skip processing if already busy to prevent
        queue buildup.

        Args:
            frame: numpy array (BGRA) to process
            confidence_threshold: OCR confidence threshold
        """
        if self._processing:
            return  # Skip frame if still processing previous
        self._processing = True
        try:
            self._process_frame_impl(frame, confidence_threshold)
        finally:
            self._processing = False

    def _process_frame_impl(self, frame, confidence_threshold: float):
        """Internal implementation of frame processing."""
        if self._ocr is None:
            return

        frame_start = time.perf_counter()
        ocr_ms = 0
        translate_ms = 0
        was_cached = False

        # Update OCR threshold from GUI setting
        self._ocr.confidence_threshold = confidence_threshold

        # OCR
        try:
            ocr_start = time.perf_counter()
            if self._mode == "inplace":
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
            if self._mode == "inplace":
                self.regions_ready.emit([])
            else:
                self.text_ready.emit("")
            return

        # Translation
        translate_start = time.perf_counter()
        if self._mode == "inplace":
            # Translate each region
            translated_regions = []
            all_cached = True
            for region in regions:
                if self._translator and region.text:
                    try:
                        translated, cached = self._translator.translate(region.text)
                        if not cached:
                            all_cached = False
                    except Exception as e:
                        logger.warning("Translation error", error=str(e), text=region.text[:50])
                        translated = region.text
                        all_cached = False
                else:
                    translated = region.text
                translated_regions.append((translated, region.bbox))
            translate_ms = int((time.perf_counter() - translate_start) * 1000)
            was_cached = all_cached and len(translated_regions) > 0

            self.regions_ready.emit(translated_regions)
        else:
            # Banner mode: single text
            if self._translator:
                try:
                    translated, was_cached = self._translator.translate(text)
                except Exception as e:
                    logger.warning("Translation error", error=str(e), text=text[:50])
                    translated = f"[{text}]"
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
