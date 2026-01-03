"""Background workers for capture, OCR, and translation."""

from typing import Optional

from PySide6.QtCore import QObject, Signal, QTimer

from ..capture import WindowCapture
from ..ocr import OCR
from ..translate import Translator


class CaptureWorker(QObject):
    """Worker for window capture with FPS tracking.

    Uses a QTimer to poll frames from the capture stream.
    Emits frame_ready signal when a new frame is available.
    The FPS comes from the capture stream itself, which tracks actual
    capture rate in its background thread.
    """

    frame_ready = Signal(object, float, dict)  # PIL Image, fps, bounds

    def __init__(self):
        super().__init__()
        self._capture: Optional[WindowCapture] = None
        self._timer = QTimer()
        self._timer.timeout.connect(self._fetch_frame)

    def set_capture(self, capture: Optional[WindowCapture]):
        """Set the capture instance."""
        self._capture = capture

    def start(self, interval_ms: int = 33):
        """Start polling for frames.

        Args:
            interval_ms: Polling interval in milliseconds (default ~30 FPS)
        """
        self._timer.setInterval(interval_ms)
        self._timer.start()

    def stop(self):
        """Stop polling for frames."""
        self._timer.stop()

    def _fetch_frame(self):
        """Fetch a frame from capture stream."""
        if self._capture is None:
            return

        frame = self._capture.get_frame()
        if frame is not None:
            # Get FPS from the capture stream (tracks actual capture rate)
            fps = self._capture.fps

            # Emit frame with bounds
            bounds = self._capture.bounds or {}
            self.frame_ready.emit(frame, fps, bounds)


class ProcessWorker(QObject):
    """Worker for OCR and translation processing.

    Processes frames through OCR and translation pipeline.
    Emits result signals for banner or inplace mode.
    """

    # Banner mode: single translated text
    text_ready = Signal(str, str, bool)  # original, translated, cached

    # Inplace mode: list of (text, bbox) regions
    regions_ready = Signal(list)  # list of (translated_text, bbox)

    def __init__(self):
        super().__init__()
        self._ocr: Optional[OCR] = None
        self._translator: Optional[Translator] = None
        self._mode = "banner"

    def set_ocr(self, ocr: Optional[OCR]):
        """Set the OCR instance."""
        self._ocr = ocr

    def set_translator(self, translator: Optional[Translator]):
        """Set the translator instance."""
        self._translator = translator

    def set_mode(self, mode: str):
        """Set the overlay mode (banner or inplace)."""
        self._mode = mode

    def process_frame(self, frame, confidence_threshold: float = 0.6):
        """Process a frame through OCR and translation.

        Args:
            frame: PIL Image to process
            confidence_threshold: OCR confidence threshold
        """
        if self._ocr is None:
            return

        # Update OCR threshold from GUI setting
        self._ocr.confidence_threshold = confidence_threshold

        # OCR
        try:
            if self._mode == "inplace":
                regions = self._ocr.extract_text_regions(frame)
                text = " ".join(r.text for r in regions if r.text)
            else:
                text = self._ocr.extract_text(frame)
                regions = []
        except Exception as e:
            print(f"OCR error: {e}")
            return

        if not text:
            if self._mode == "inplace":
                self.regions_ready.emit([])
            else:
                self.text_ready.emit("", "", False)
            return

        # Translation
        cached = False

        if self._mode == "inplace":
            # Translate each region
            translated_regions = []
            for region in regions:
                if self._translator and region.text:
                    try:
                        translated, was_cached = self._translator.translate(region.text)
                        cached = cached or was_cached
                    except Exception:
                        translated = region.text
                else:
                    translated = region.text
                translated_regions.append((translated, region.bbox))

            self.regions_ready.emit(translated_regions)
        else:
            # Banner mode: single text
            if self._translator:
                try:
                    translated, cached = self._translator.translate(text)
                except Exception:
                    translated = f"[{text}]"
            else:
                translated = text

            self.text_ready.emit(text, translated, cached)
