"""Pluggable backends for OCR and translation."""

from .base import (
    Language,
    OCRBackend,
    OCRBackendInfo,
    OCRResult,
    TranslationBackend,
    TranslationBackendInfo,
)
from .model_manager import ModelManager, ModelStatus, get_model_manager
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
    "ModelManager",
    "ModelStatus",
    "get_model_manager",
]
