"""EasyOCR backend for Latin-based languages."""

from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from ... import log
from ...capture.convert import bgra_to_rgb
from ..base import Language, OCRBackend, OCRBackendInfo, OCRResult

logger = log.get_logger()

# EasyOCR model directory
EASYOCR_MODEL_DIR = Path.home() / ".EasyOCR" / "model"

# Detection model (shared across all languages)
DETECTION_MODEL = "craft_mlt_25k.pth"

# Map Language enum to EasyOCR recognition model filenames
LANGUAGE_TO_MODEL_FILE = {
    Language.ENGLISH: "english_g2.pth",
    Language.FRENCH: "french_g2.pth",
    Language.GERMAN: "german_g2.pth",
    Language.SPANISH: "spanish_g2.pth",
    Language.ITALIAN: "italian_g2.pth",
    Language.PORTUGUESE: "portuguese_g2.pth",
    Language.DUTCH: "dutch_g2.pth",
    Language.POLISH: "polish_g2.pth",
}

# Default confidence threshold (0-1 scale)
DEFAULT_CONFIDENCE_THRESHOLD = 0.6

# Map Language enum to EasyOCR language codes
LANGUAGE_TO_EASYOCR = {
    Language.ENGLISH: "en",
    Language.FRENCH: "fr",
    Language.GERMAN: "de",
    Language.SPANISH: "es",
    Language.ITALIAN: "it",
    Language.PORTUGUESE: "pt",
    Language.DUTCH: "nl",
    Language.POLISH: "pl",
}

# All Latin-script languages supported by this backend
SUPPORTED_LANGUAGES = list(LANGUAGE_TO_EASYOCR.keys())


class EasyOCRBackend(OCRBackend):
    """Extracts text from images using EasyOCR.

    EasyOCR is a deep learning-based OCR engine that works well with
    Latin-based scripts. It supports 80+ languages and automatically
    downloads models on first use. GPU acceleration is supported.
    """

    def __init__(
        self,
        language: Language = Language.ENGLISH,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    ):
        """Initialize EasyOCR backend.

        Args:
            language: The language to use for OCR.
            confidence_threshold: Minimum confidence threshold (0.0-1.0).
        """
        super().__init__(confidence_threshold)
        self._language = language
        self._easyocr_lang = LANGUAGE_TO_EASYOCR.get(language, "en")
        self._reader = None
        self._loaded = False

    @classmethod
    def get_info(cls) -> OCRBackendInfo:
        """Get metadata about this backend."""
        return OCRBackendInfo(
            id="easyocr",
            name="EasyOCR",
            supported_languages=SUPPORTED_LANGUAGES,
            model_size_mb=100,  # Approximate size for Latin models
            license="Apache-2.0",
            description="Deep learning OCR for Latin-based languages (auto-downloads models)",
        )

    @classmethod
    def is_model_installed(cls, language: Language) -> bool:
        """Check if EasyOCR models are downloaded for a specific language.

        Args:
            language: The language to check.

        Returns:
            True if models are installed, False otherwise.
        """
        # Check if detection model exists
        detection_path = EASYOCR_MODEL_DIR / DETECTION_MODEL
        if not detection_path.exists():
            return False

        # Check if recognition model exists for this language
        model_file = LANGUAGE_TO_MODEL_FILE.get(language)
        if not model_file:
            return False

        recognition_path = EASYOCR_MODEL_DIR / model_file
        return recognition_path.exists()

    def load(self) -> None:
        """Load EasyOCR reader and download models if needed.

        Models are automatically downloaded to ~/.EasyOCR/ on first use.
        """
        if self._loaded:
            return

        logger.info("loading easyocr", language=self._easyocr_lang)

        try:
            import easyocr

            # Create reader - this will download models if not present
            # gpu=True will use CUDA if available, falls back to CPU otherwise
            self._reader = easyocr.Reader(
                [self._easyocr_lang],
                gpu=True,  # Auto-detects GPU availability
                verbose=False,
            )
            logger.info("easyocr ready", language=self._easyocr_lang)
            self._loaded = True
        except Exception as e:
            raise RuntimeError(f"Failed to load EasyOCR: {e}") from e

    def is_loaded(self) -> bool:
        """Check if EasyOCR is loaded."""
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

        # Convert BGRA to RGB
        rgb_array = bgra_to_rgb(image)

        # Run EasyOCR
        results = self._reader.readtext(
            rgb_array,
            detail=1,  # Return confidence scores
            paragraph=False,
        )

        # Filter by confidence and join text
        texts = []
        for bbox, text, conf in results:
            if conf >= self._confidence_threshold:
                texts.append(text)

        return " ".join(texts)

    def extract_text_regions(self, image: NDArray[np.uint8]) -> list[OCRResult]:
        """Extract text regions from an image with bounding boxes.

        Args:
            image: Numpy array (H, W, 4) in BGRA format.

        Returns:
            List of OCRResult objects with text and bounding boxes.
        """
        if not self._loaded:
            self.load()

        # Convert BGRA to RGB
        rgb_array = bgra_to_rgb(image)

        # Run EasyOCR with detailed output
        results = self._reader.readtext(
            rgb_array,
            detail=1,
            paragraph=False,
        )

        regions = []
        for bbox, text, conf in results:
            if conf < self._confidence_threshold:
                continue

            text = self._clean_text(text)
            if not text:
                continue

            # EasyOCR returns bbox as [[x1,y1], [x2,y1], [x2,y2], [x1,y2]]
            # Convert to {x, y, width, height} format
            x_coords = [point[0] for point in bbox]
            y_coords = [point[1] for point in bbox]
            min_x = int(min(x_coords))
            min_y = int(min(y_coords))
            max_x = int(max(x_coords))
            max_y = int(max(y_coords))

            bbox_dict = {
                "x": min_x,
                "y": min_y,
                "width": max_x - min_x,
                "height": max_y - min_y,
            }

            regions.append(OCRResult(text=text, bbox=bbox_dict))

        return regions

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
