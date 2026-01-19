"""Abstract base classes for OCR and translation backends."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum

import numpy as np
from numpy.typing import NDArray


class Language(Enum):
    """Supported languages for OCR and translation."""

    JAPANESE = "ja"
    ENGLISH = "en"
    FRENCH = "fr"
    GERMAN = "de"
    SPANISH = "es"
    ITALIAN = "it"
    PORTUGUESE = "pt"
    DUTCH = "nl"
    POLISH = "pl"
    RUSSIAN = "ru"
    CHINESE = "zh"
    KOREAN = "ko"

    @property
    def display_name(self) -> str:
        """Human-readable name for the language."""
        names = {
            Language.JAPANESE: "Japanese",
            Language.ENGLISH: "English",
            Language.FRENCH: "French",
            Language.GERMAN: "German",
            Language.SPANISH: "Spanish",
            Language.ITALIAN: "Italian",
            Language.PORTUGUESE: "Portuguese",
            Language.DUTCH: "Dutch",
            Language.POLISH: "Polish",
            Language.RUSSIAN: "Russian",
            Language.CHINESE: "Chinese",
            Language.KOREAN: "Korean",
        }
        return names.get(self, self.value)

    @property
    def uses_latin_script(self) -> bool:
        """Whether this language uses Latin script (for OCR selection)."""
        latin_languages = {
            Language.ENGLISH,
            Language.FRENCH,
            Language.GERMAN,
            Language.SPANISH,
            Language.ITALIAN,
            Language.PORTUGUESE,
            Language.DUTCH,
            Language.POLISH,
        }
        return self in latin_languages


@dataclass
class OCRResult:
    """Result from OCR extraction with optional bounding box."""

    text: str
    bbox: dict | None = None  # {"x": int, "y": int, "width": int, "height": int}


@dataclass
class OCRBackendInfo:
    """Metadata about an OCR backend."""

    id: str
    name: str
    supported_languages: list[Language]
    model_size_mb: int
    license: str
    description: str = ""


@dataclass
class TranslationBackendInfo:
    """Metadata about a translation backend."""

    id: str
    name: str
    source_language: Language
    target_language: Language
    model_size_mb: int
    license: str
    description: str = ""
    is_default: bool = False
    huggingface_repo: str = ""


class OCRBackend(ABC):
    """Abstract base class for OCR backends."""

    def __init__(self, confidence_threshold: float = 0.6):
        """Initialize OCR backend.

        Args:
            confidence_threshold: Minimum confidence threshold for text detection (0.0-1.0).
        """
        self._confidence_threshold = confidence_threshold

    @property
    def confidence_threshold(self) -> float:
        """Get the confidence threshold."""
        return self._confidence_threshold

    @confidence_threshold.setter
    def confidence_threshold(self, value: float) -> None:
        """Set the confidence threshold."""
        self._confidence_threshold = value

    @abstractmethod
    def load(self) -> None:
        """Load the OCR model.

        Raises:
            Exception: If model fails to load.
        """
        pass

    @abstractmethod
    def extract_text(self, image: NDArray[np.uint8]) -> str:
        """Extract text from an image.

        Args:
            image: Numpy array (H, W, 4) in BGRA format.

        Returns:
            Extracted text string.
        """
        pass

    @abstractmethod
    def extract_text_regions(self, image: NDArray[np.uint8]) -> list[OCRResult]:
        """Extract text regions from an image with bounding boxes.

        Args:
            image: Numpy array (H, W, 4) in BGRA format.

        Returns:
            List of OCRResult objects with text and bounding boxes.
        """
        pass

    @abstractmethod
    def is_loaded(self) -> bool:
        """Check if the model is loaded.

        Returns:
            True if model is loaded, False otherwise.
        """
        pass

    @classmethod
    @abstractmethod
    def get_info(cls) -> OCRBackendInfo:
        """Get metadata about this backend.

        Returns:
            OCRBackendInfo with backend details.
        """
        pass


class TranslationBackend(ABC):
    """Abstract base class for translation backends."""

    @abstractmethod
    def load(self) -> None:
        """Load the translation model.

        Raises:
            Exception: If model fails to load.
        """
        pass

    @abstractmethod
    def translate(self, text: str) -> str:
        """Translate text.

        Args:
            text: Source text to translate.

        Returns:
            Translated text.
        """
        pass

    @abstractmethod
    def is_loaded(self) -> bool:
        """Check if the model is loaded.

        Returns:
            True if model is loaded, False otherwise.
        """
        pass

    @classmethod
    @abstractmethod
    def get_info(cls) -> TranslationBackendInfo:
        """Get metadata about this backend.

        Returns:
            TranslationBackendInfo with backend details.
        """
        pass
