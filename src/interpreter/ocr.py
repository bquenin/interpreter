"""OCR module using MeikiOCR for Japanese game text extraction.

This module provides backward compatibility with the original OCR interface.
The actual implementation has moved to interpreter.backends.ocr.meiki.
"""

from .backends.base import OCRResult
from .backends.ocr.meiki import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    MeikiOCRBackend,
)

# Re-export OCRResult for backward compatibility
__all__ = ["OCR", "OCRResult"]


class OCR(MeikiOCRBackend):
    """Backward-compatible OCR class.

    This is a thin wrapper around MeikiOCRBackend for backward compatibility.
    New code should use MeikiOCRBackend directly from interpreter.backends.ocr.
    """

    pass
