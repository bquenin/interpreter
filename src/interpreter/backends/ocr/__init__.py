"""OCR backend implementations."""

from .easyocr import EasyOCRBackend
from .meiki import MeikiOCRBackend
from .paddleocr_backend import PaddleOCRBackend

__all__ = [
    "EasyOCRBackend",
    "MeikiOCRBackend",
    "PaddleOCRBackend",
]
