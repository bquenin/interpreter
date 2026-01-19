"""Tesseract OCR backend for Latin-based languages."""

import numpy as np
from numpy.typing import NDArray

from ... import log
from ...capture.convert import bgra_to_rgb
from ..base import Language, OCRBackend, OCRBackendInfo, OCRResult

logger = log.get_logger()

# Default confidence threshold for Tesseract (0-100 scale internally, normalized to 0-1)
DEFAULT_CONFIDENCE_THRESHOLD = 0.6

# Map Language enum to Tesseract language codes
LANGUAGE_TO_TESSERACT = {
    Language.ENGLISH: "eng",
    Language.FRENCH: "fra",
    Language.GERMAN: "deu",
    Language.SPANISH: "spa",
    Language.ITALIAN: "ita",
    Language.PORTUGUESE: "por",
    Language.DUTCH: "nld",
    Language.POLISH: "pol",
}

# All Latin-script languages supported by this backend
SUPPORTED_LANGUAGES = list(LANGUAGE_TO_TESSERACT.keys())


class TesseractOCRBackend(OCRBackend):
    """Extracts text from images using Tesseract OCR.

    Tesseract is a general-purpose OCR engine that works well with
    Latin-based scripts. It supports many languages and is suitable
    for game text in English, French, German, Spanish, etc.
    """

    def __init__(
        self,
        language: Language = Language.ENGLISH,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    ):
        """Initialize Tesseract backend.

        Args:
            language: The language to use for OCR.
            confidence_threshold: Minimum confidence threshold (0.0-1.0).
        """
        super().__init__(confidence_threshold)
        self._language = language
        self._tesseract_lang = LANGUAGE_TO_TESSERACT.get(language, "eng")
        self._loaded = False

    @classmethod
    def get_info(cls) -> OCRBackendInfo:
        """Get metadata about this backend."""
        return OCRBackendInfo(
            id="tesseract",
            name="Tesseract",
            supported_languages=SUPPORTED_LANGUAGES,
            model_size_mb=15,  # Approximate size per language
            license="Apache-2.0",
            description="General-purpose OCR for Latin-based languages",
        )

    def load(self) -> None:
        """Load/verify Tesseract is available.

        Raises:
            Exception: If Tesseract is not installed.
        """
        if self._loaded:
            return

        logger.info("loading tesseract", language=self._tesseract_lang)

        try:
            import pytesseract

            # Verify Tesseract is installed by getting version
            version = pytesseract.get_tesseract_version()
            logger.info("tesseract ready", version=str(version), language=self._tesseract_lang)
            self._loaded = True
        except Exception as e:
            raise RuntimeError(
                f"Tesseract OCR is not installed or not in PATH. "
                f"Please install Tesseract: https://github.com/tesseract-ocr/tesseract"
            ) from e

    def is_loaded(self) -> bool:
        """Check if Tesseract is available."""
        return self._loaded

    def extract_text(self, image: NDArray[np.uint8]) -> str:
        """Extract text from an image.

        Args:
            image: Numpy array (H, W, 4) in BGRA format.

        Returns:
            Extracted text string.
        """
        if not self._loaded:
            self.load()

        import pytesseract
        from PIL import Image

        # Convert BGRA to RGB
        rgb_array = bgra_to_rgb(image)
        pil_image = Image.fromarray(rgb_array)

        # Run Tesseract
        text = pytesseract.image_to_string(
            pil_image,
            lang=self._tesseract_lang,
            config="--psm 6",  # Assume uniform block of text
        )

        return self._clean_text(text)

    def extract_text_regions(self, image: NDArray[np.uint8]) -> list[OCRResult]:
        """Extract text regions from an image with bounding boxes.

        Args:
            image: Numpy array (H, W, 4) in BGRA format.

        Returns:
            List of OCRResult objects with text and bounding boxes.
        """
        if not self._loaded:
            self.load()

        import pytesseract
        from PIL import Image

        # Convert BGRA to RGB
        rgb_array = bgra_to_rgb(image)
        pil_image = Image.fromarray(rgb_array)

        # Get detailed data with bounding boxes
        data = pytesseract.image_to_data(
            pil_image,
            lang=self._tesseract_lang,
            config="--psm 6",
            output_type=pytesseract.Output.DICT,
        )

        # Group words into lines and filter by confidence
        regions = []
        current_line = []
        current_line_num = -1
        current_block_num = -1

        n_boxes = len(data["text"])
        for i in range(n_boxes):
            text = data["text"][i].strip()
            conf = data["conf"][i]
            line_num = data["line_num"][i]
            block_num = data["block_num"][i]

            # Skip empty text or low confidence
            if not text or conf < 0:
                continue

            # Normalize confidence from 0-100 to 0-1
            normalized_conf = conf / 100.0

            if normalized_conf < self._confidence_threshold:
                continue

            # Check if we're on a new line/block
            if line_num != current_line_num or block_num != current_block_num:
                # Save previous line if it exists
                if current_line:
                    regions.append(self._line_to_region(current_line))
                current_line = []
                current_line_num = line_num
                current_block_num = block_num

            # Add word to current line
            current_line.append({
                "text": text,
                "x": data["left"][i],
                "y": data["top"][i],
                "w": data["width"][i],
                "h": data["height"][i],
                "conf": normalized_conf,
            })

        # Don't forget the last line
        if current_line:
            regions.append(self._line_to_region(current_line))

        return regions

    def _line_to_region(self, words: list[dict]) -> OCRResult:
        """Convert a list of words into an OCRResult.

        Args:
            words: List of word dicts with text, x, y, w, h keys.

        Returns:
            OCRResult with combined text and bounding box.
        """
        # Combine text
        text = " ".join(word["text"] for word in words)
        text = self._clean_text(text)

        # Compute bounding box
        min_x = min(word["x"] for word in words)
        min_y = min(word["y"] for word in words)
        max_x = max(word["x"] + word["w"] for word in words)
        max_y = max(word["y"] + word["h"] for word in words)

        bbox = {
            "x": min_x,
            "y": min_y,
            "width": max_x - min_x,
            "height": max_y - min_y,
        }

        return OCRResult(text=text, bbox=bbox)

    def _clean_text(self, text: str) -> str:
        """Clean extracted text.

        Args:
            text: Raw extracted text.

        Returns:
            Cleaned text.
        """
        if not text:
            return ""

        # Remove extra whitespace
        text = " ".join(text.split())

        # Strip leading/trailing whitespace
        text = text.strip()

        return text
