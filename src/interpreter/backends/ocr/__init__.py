"""OCR backend implementations."""

from .meiki import MeikiOCRBackend
from .tesseract import TesseractOCRBackend

__all__ = [
    "MeikiOCRBackend",
    "TesseractOCRBackend",
]
