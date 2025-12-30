"""OCR module using MeikiOCR for Japanese game text extraction."""

import numpy as np
from PIL import Image


class OCR:
    """Extracts Japanese text from images using MeikiOCR.

    MeikiOCR is specifically trained on Japanese video game text,
    providing significantly better accuracy on pixel fonts than
    general-purpose OCR.
    """

    def __init__(self, confidence_threshold: float = 0.6, debug: bool = False):
        """Initialize OCR (lazy loading of model).

        Args:
            confidence_threshold: Minimum average confidence per line (0.0-1.0).
                Lines below this threshold are filtered out.
            debug: If True, print per-character confidence scores.
        """
        self._model = None
        self._confidence_threshold = confidence_threshold
        self._debug = debug

    def load(self) -> None:
        """Load the MeikiOCR model."""
        if self._model is not None:
            return

        print("Loading MeikiOCR...")
        from meikiocr import MeikiOCR
        self._model = MeikiOCR()
        print("MeikiOCR ready.")

    def extract_text(self, image: Image.Image) -> str:
        """Extract Japanese text from an image.

        Args:
            image: PIL Image to extract text from.

        Returns:
            Extracted text string.
        """
        # Ensure model is loaded
        if self._model is None:
            self.load()

        # Convert to numpy array (RGB) - no preprocessing needed
        # Benchmarks showed raw images work best with MeikiOCR
        img_array = np.array(image.convert('RGB'))

        # Run MeikiOCR
        results = self._model.run_ocr(img_array)

        # Extract text from results, filtering by confidence
        texts = []
        for result in results:
            if 'text' not in result:
                continue

            # Calculate average confidence for this line
            chars = result.get('chars', [])
            if chars:
                avg_conf = sum(c['conf'] for c in chars) / len(chars)
            else:
                avg_conf = 0.0

            # Print per-character confidence in debug mode
            if self._debug and chars:
                char_info = ' '.join(
                    f"{c['char']}({c['conf']:.2f})" for c in chars
                )
                status = "✓" if avg_conf >= self._confidence_threshold else "✗"
                print(f"[DBG] {char_info} → avg: {avg_conf:.2f} {status}")

            # Filter by confidence threshold
            if avg_conf >= self._confidence_threshold:
                texts.append(result['text'])

        text = ''.join(texts)

        # Clean up the text
        text = self._clean_text(text)

        return text

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

    def is_loaded(self) -> bool:
        """Check if the model is loaded.

        Returns:
            True if model is loaded, False otherwise.
        """
        return self._model is not None
