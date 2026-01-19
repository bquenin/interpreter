"""Pluggable backends for OCR and translation."""

from .base import (
    Language,
    OCRBackend,
    OCRBackendInfo,
    TranslationBackend,
    TranslationBackendInfo,
)
from .registry import BackendRegistry

__all__ = [
    "Language",
    "OCRBackend",
    "OCRBackendInfo",
    "TranslationBackend",
    "TranslationBackendInfo",
    "BackendRegistry",
]
