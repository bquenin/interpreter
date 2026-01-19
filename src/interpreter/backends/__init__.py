"""Pluggable backends for OCR and translation."""

from .base import (
    Language,
    OCRBackend,
    OCRBackendInfo,
    OCRResult,
    TranslationBackend,
    TranslationBackendInfo,
)
from .registry import BackendRegistry, get_registry

__all__ = [
    "Language",
    "OCRBackend",
    "OCRBackendInfo",
    "OCRResult",
    "TranslationBackend",
    "TranslationBackendInfo",
    "BackendRegistry",
    "get_registry",
]
