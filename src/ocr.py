"""OCR module using MeikiOCR for Japanese game text extraction."""

import numpy as np
from PIL import Image


class OCR:
    """Extracts Japanese text from images using MeikiOCR.

    MeikiOCR is specifically trained on Japanese video game text,
    providing significantly better accuracy on pixel fonts than
    general-purpose OCR.
    """

    def __init__(self, confidence_threshold: float = 0.0):
        """Initialize OCR (lazy loading of model).

        Args:
            confidence_threshold: Minimum confidence score for OCR results (0.0-1.0).
                                  Results below this threshold are filtered out.
        """
        self._model = None
        self.confidence_threshold = confidence_threshold

    def load(self) -> None:
        """Load the MeikiOCR model."""
        if self._model is not None:
            return

        print("Loading MeikiOCR model...")
        from meikiocr import MeikiOCR
        self._model = MeikiOCR()
        print("MeikiOCR model loaded.")

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

            # Filter by confidence if specified
            if self.confidence_threshold > 0:
                confidence = result.get('confidence', 1.0)
                if confidence < self.confidence_threshold:
                    continue

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
