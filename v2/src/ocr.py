"""OCR module using manga-ocr for Japanese text extraction."""

from typing import Optional

from PIL import Image


class OCR:
    """Extracts Japanese text from images using manga-ocr."""

    def __init__(self):
        """Initialize OCR (lazy loading of model)."""
        self._model = None

    def _ensure_model(self):
        """Lazily load the manga-ocr model on first use."""
        if self._model is None:
            print("Loading manga-ocr model (this may take a moment on first run)...")
            from manga_ocr import MangaOcr
            self._model = MangaOcr()
            print("manga-ocr model loaded.")

    def extract_text(self, image: Image.Image) -> str:
        """Extract Japanese text from an image.

        Args:
            image: PIL Image to extract text from.

        Returns:
            Extracted text string.
        """
        self._ensure_model()

        # manga-ocr works directly with PIL images
        text = self._model(image)

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
