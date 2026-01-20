"""PaddleOCR backend for Latin-based languages."""

from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray

from ... import log
from ...capture.convert import bgra_to_rgb
from ..base import Language, OCRBackend, OCRBackendInfo, OCRResult

# Pixel font preprocessing: downscale first, then upscale with NEAREST neighbor
# This preserves sharp pixel edges that get blurred by other interpolation methods
# Step 1: Downscale large images to this size (for performance)
DOWNSCALE_DIMENSION = 300
# Step 2: Upscale with NEAREST neighbor by this factor (preserves pixel edges)
# 4x works best for pixel fonts: detects punctuation (?!) and standalone "I"
# Trade-off: apostrophes may be slightly worse (I'm -> Fm) but translation handles it
NEAREST_UPSCALE_FACTOR = 4
# Final OCR dimension will be ~DOWNSCALE_DIMENSION * NEAREST_UPSCALE_FACTOR = 1200

logger = log.get_logger()

# PaddleOCR model directory
PADDLEOCR_MODEL_DIR = Path.home() / ".paddleocr"

# Default confidence threshold (0-1 scale)
# Lower threshold to catch single-char detections with borderline confidence
DEFAULT_CONFIDENCE_THRESHOLD = 0.55

# Map Language enum to PaddleOCR language codes
LANGUAGE_TO_PADDLEOCR = {
    Language.ENGLISH: "en",
    Language.FRENCH: "fr",
    Language.GERMAN: "german",
    Language.SPANISH: "es",
    Language.ITALIAN: "it",
    Language.PORTUGUESE: "pt",
    Language.DUTCH: "nl",
    Language.POLISH: "pl",
    Language.RUSSIAN: "ru",
}

# All languages supported by this backend
SUPPORTED_LANGUAGES = list(LANGUAGE_TO_PADDLEOCR.keys())


class PaddleOCRBackend(OCRBackend):
    """Extracts text from images using PaddleOCR.

    PaddleOCR is a deep learning-based OCR engine from Baidu that works well
    with various fonts including pixel/retro game fonts. It supports 80+
    languages and automatically downloads models on first use.
    """

    def __init__(
        self,
        language: Language = Language.ENGLISH,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    ):
        """Initialize PaddleOCR backend.

        Args:
            language: The language to use for OCR.
            confidence_threshold: Minimum confidence threshold (0.0-1.0).
        """
        super().__init__(confidence_threshold)
        self._language = language
        self._paddleocr_lang = LANGUAGE_TO_PADDLEOCR.get(language, "en")
        self._ocr = None
        self._loaded = False

    @classmethod
    def get_info(cls) -> OCRBackendInfo:
        """Get metadata about this backend."""
        return OCRBackendInfo(
            id="paddleocr",
            name="PaddleOCR",
            supported_languages=SUPPORTED_LANGUAGES,
            model_size_mb=150,  # Approximate size
            license="Apache-2.0",
            description="Baidu's deep learning OCR with good pixel font support (auto-downloads models)",
        )

    @classmethod
    def is_model_installed(cls, language: Language) -> bool:
        """Check if PaddleOCR models are downloaded for a specific language.

        PaddleOCR auto-downloads models on first use, so we always return True
        to allow the load() method to handle downloading transparently.

        Args:
            language: The language to check.

        Returns:
            Always True since PaddleOCR handles auto-download.
        """
        # PaddleOCR auto-downloads models during initialization,
        # so we return True to allow transparent downloading
        return True

    def load(self) -> None:
        """Load PaddleOCR and download models if needed.

        Models are automatically downloaded to ~/.paddleocr/ on first use.
        """
        if self._loaded:
            return

        logger.info("loading paddleocr", language=self._paddleocr_lang)

        try:
            from paddleocr import PaddleOCR

            # Create OCR instance - this will download models if not present
            # PaddleOCR 2.7.x API
            self._ocr = PaddleOCR(
                lang=self._paddleocr_lang,
                use_angle_cls=False,  # Disable angle classification for speed
                use_gpu=False,  # CPU mode (GPU requires paddlepaddle-gpu)
                show_log=False,  # Reduce log verbosity
            )
            logger.info("paddleocr ready", language=self._paddleocr_lang)
            self._loaded = True
        except Exception as e:
            raise RuntimeError(f"Failed to load PaddleOCR: {e}") from e

    def is_loaded(self) -> bool:
        """Check if PaddleOCR is loaded."""
        return self._loaded

    def _preprocess_for_pixel_fonts(
        self, rgb_array: NDArray[np.uint8]
    ) -> tuple[NDArray[np.uint8], float]:
        """Preprocess image for better pixel font recognition.

        Uses a two-step approach:
        1. Downscale large images to DOWNSCALE_DIMENSION (for performance)
        2. Upscale with NEAREST neighbor (preserves sharp pixel edges)

        Args:
            rgb_array: RGB image array.

        Returns:
            Tuple of (processed image, scale factor for bbox conversion).
        """
        h, w = rgb_array.shape[:2]
        scale = 1.0

        # Step 1: Downscale if image is larger than target
        if max(h, w) > DOWNSCALE_DIMENSION:
            scale = DOWNSCALE_DIMENSION / max(h, w)
            new_w = int(w * scale)
            new_h = int(h * scale)
            rgb_array = cv2.resize(
                rgb_array, (new_w, new_h), interpolation=cv2.INTER_AREA
            )

        # Step 2: Upscale with NEAREST neighbor to sharpen pixel edges
        h, w = rgb_array.shape[:2]
        upscale_w = w * NEAREST_UPSCALE_FACTOR
        upscale_h = h * NEAREST_UPSCALE_FACTOR
        rgb_array = cv2.resize(
            rgb_array, (upscale_w, upscale_h), interpolation=cv2.INTER_NEAREST
        )

        # Adjust scale factor
        final_scale = scale * NEAREST_UPSCALE_FACTOR

        return rgb_array, final_scale

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

        # Preprocess for pixel fonts (downscale + NEAREST upscale)
        rgb_array, _ = self._preprocess_for_pixel_fonts(rgb_array)

        # Run PaddleOCR
        results = self._ocr.ocr(rgb_array)

        # Filter by confidence and collect text with positions for sorting
        text_items = []  # List of (y, x, text) for sorting by reading order
        if results and len(results) > 0:
            result = results[0]
            # New PaddleOCR v3+ returns OCRResult objects with dict-like access
            if hasattr(result, 'keys') and 'rec_texts' in result.keys():
                rec_texts = result['rec_texts'] or []
                rec_scores = result['rec_scores'] or []
                rec_polys = result['rec_polys'] or []
                # Debug: log all detections with confidence
                logger.debug(
                    "paddleocr detections",
                    items=[(t, f"{s:.2f}") for t, s in zip(rec_texts, rec_scores)]
                )
                for text, conf, bbox in zip(rec_texts, rec_scores, rec_polys):
                    if conf >= self._confidence_threshold and text:
                        # Get top-left corner for sorting (min y, min x)
                        if len(bbox) >= 4:
                            min_y = min(point[1] for point in bbox)
                            min_x = min(point[0] for point in bbox)
                            text_items.append((min_y, min_x, text))
            # Legacy format: list of [bbox, (text, conf)]
            elif isinstance(result, list):
                for line in result:
                    if line and len(line) >= 2:
                        bbox, (text, conf) = line
                        if conf >= self._confidence_threshold and text:
                            min_y = min(point[1] for point in bbox)
                            min_x = min(point[0] for point in bbox)
                            text_items.append((min_y, min_x, text))

        # Sort by reading order: group by approximate line (Y), then sort by X within each line
        if text_items:
            # Sort primarily by Y
            text_items.sort(key=lambda item: item[0])

            # Group into lines based on Y proximity (items within 30 pixels are same line)
            # Increased from 20 to handle single-char detection at slightly different Y positions
            line_threshold = 30
            lines = []
            current_line = [text_items[0]]

            for item in text_items[1:]:
                if abs(item[0] - current_line[0][0]) < line_threshold:
                    current_line.append(item)
                else:
                    lines.append(current_line)
                    current_line = [item]
            lines.append(current_line)

            # Sort each line by X (left to right) and flatten
            texts = []
            for line in lines:
                line.sort(key=lambda item: item[1])
                texts.extend(item[2] for item in line)
        else:
            texts = []

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

        # Preprocess for pixel fonts (downscale + NEAREST upscale)
        rgb_array, scale = self._preprocess_for_pixel_fonts(rgb_array)

        # Run PaddleOCR
        results = self._ocr.ocr(rgb_array)

        # Scale factor to convert bbox coords back to original size
        inv_scale = 1.0 / scale

        regions = []
        if results and len(results) > 0:
            result = results[0]
            # New PaddleOCR v3+ returns OCRResult objects with dict-like access
            if hasattr(result, 'keys') and 'rec_texts' in result.keys():
                rec_texts = result['rec_texts'] or []
                rec_scores = result['rec_scores'] or []
                rec_polys = result['rec_polys'] or []

                for text, conf, bbox in zip(rec_texts, rec_scores, rec_polys):
                    if conf < self._confidence_threshold:
                        continue

                    text = self._clean_text(text)
                    if not text:
                        continue

                    # rec_polys contains polygon coordinates
                    # Convert to {x, y, width, height} format and scale back
                    if len(bbox) >= 4:
                        x_coords = [point[0] * inv_scale for point in bbox]
                        y_coords = [point[1] * inv_scale for point in bbox]
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

            # Legacy format: list of [bbox, (text, conf)]
            elif isinstance(result, list):
                for line in result:
                    if not line or len(line) < 2:
                        continue

                    bbox, (text, conf) = line

                    if conf < self._confidence_threshold:
                        continue

                    text = self._clean_text(text)
                    if not text:
                        continue

                    # PaddleOCR returns bbox as [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                    # Scale back to original coordinates
                    x_coords = [point[0] * inv_scale for point in bbox]
                    y_coords = [point[1] * inv_scale for point in bbox]
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
