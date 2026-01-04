"""Background workers for OCR and translation."""

from PySide6.QtCore import QObject, Signal

from .. import log
from ..ocr import OCR
from ..translate import Translator

logger = log.get_logger()


class ProcessWorker(QObject):
    """Worker for OCR and translation processing.

    Processes frames through OCR and translation pipeline.
    Emits result signals for banner or inplace mode.
    """

    # Banner mode: single translated text
    text_ready = Signal(str)  # translated text

    # Inplace mode: list of (text, bbox) regions
    regions_ready = Signal(list)  # list of (translated_text, bbox)

    def __init__(self):
        super().__init__()
        self._ocr: OCR | None = None
        self._translator: Translator | None = None
        self._mode = "banner"

    def set_ocr(self, ocr: OCR | None):
        """Set the OCR instance."""
        self._ocr = ocr

    def set_translator(self, translator: Translator | None):
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
            logger.error("OCR error", error=str(e))
            return

        if not text:
            if self._mode == "inplace":
                self.regions_ready.emit([])
            else:
                self.text_ready.emit("")
            return

        # Translation
        if self._mode == "inplace":
            # Translate each region
            translated_regions = []
            for region in regions:
                if self._translator and region.text:
                    try:
                        translated, _ = self._translator.translate(region.text)
                    except Exception as e:
                        logger.warning("Translation error", error=str(e), text=region.text[:50])
                        translated = region.text
                else:
                    translated = region.text
                translated_regions.append((translated, region.bbox))

            self.regions_ready.emit(translated_regions)
        else:
            # Banner mode: single text
            if self._translator:
                try:
                    translated, _ = self._translator.translate(text)
                except Exception as e:
                    logger.warning("Translation error", error=str(e), text=text[:50])
                    translated = f"[{text}]"
            else:
                translated = text

            self.text_ready.emit(translated)
