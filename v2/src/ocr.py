"""OCR module using MeikiOCR for Japanese game text extraction."""

import cv2
import numpy as np
from PIL import Image


class OCR:
    """Extracts Japanese text from images using MeikiOCR.

    MeikiOCR is specifically trained on Japanese video game text,
    providing significantly better accuracy on pixel fonts than
    general-purpose OCR like manga-ocr.
    """

    def __init__(self):
        """Initialize OCR (lazy loading of model)."""
        self._model = None

    def _ensure_model(self):
        """Lazily load the MeikiOCR model on first use."""
        if self._model is None:
            print("Loading MeikiOCR model (this may take a moment on first run)...")
            from meikiocr import MeikiOCR
            self._model = MeikiOCR()
            print("MeikiOCR model loaded.")

    def _preprocess(self, image: Image.Image) -> np.ndarray:
        """Preprocess image for better OCR on pixel fonts.

        Applies Otsu binarization only. Benchmark showed that 4x upscaling
        actually hurts MeikiOCR accuracy.

        Args:
            image: PIL Image to preprocess.

        Returns:
            Preprocessed numpy array (RGB).
        """
        img_array = np.array(image)

        # Convert to grayscale
        if len(img_array.shape) == 3:
            gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
        else:
            gray = img_array

        # Otsu binarization (auto threshold) - no upscaling needed for MeikiOCR
        _, binary = cv2.threshold(
            gray, 0, 255,
            cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )

        # Convert to RGB numpy array for MeikiOCR
        rgb = cv2.cvtColor(binary, cv2.COLOR_GRAY2RGB)
        return rgb

    def extract_text(self, image: Image.Image, preprocess: bool = True) -> str:
        """Extract Japanese text from an image.

        Args:
            image: PIL Image to extract text from.
            preprocess: Whether to apply preprocessing for pixel fonts.

        Returns:
            Extracted text string.
        """
        self._ensure_model()

        # Convert to numpy array
        if preprocess:
            img_array = self._preprocess(image)
        else:
            img_array = np.array(image.convert('RGB'))

        # Run MeikiOCR
        results = self._model.run_ocr(img_array)

        # Extract text from results
        texts = []
        for result in results:
            if 'text' in result:
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
