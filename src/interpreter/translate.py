"""Translation module using Sugoi V4 for offline Japanese to English.

This module provides backward compatibility with the original translation interface.
The actual implementation has moved to interpreter.backends.translation.sugoi.
"""

from .backends.translation.sugoi import (
    DEFAULT_CACHE_SIZE,
    DEFAULT_SIMILARITY_THRESHOLD,
    SugoiTranslationBackend,
    TranslationCache,
    _get_short_path,
    _get_sugoi_model_path,
    _validate_model_files,
    text_similarity,
)
from .models import ModelLoadError

# Re-export for backward compatibility
__all__ = [
    "Translator",
    "TranslationCache",
    "text_similarity",
    "ModelLoadError",
]


class Translator(SugoiTranslationBackend):
    """Backward-compatible Translator class.

    This is a thin wrapper around SugoiTranslationBackend that maintains
    the original API returning (text, was_cached) tuples.

    New code should use SugoiTranslationBackend directly from
    interpreter.backends.translation.sugoi.
    """

    def translate(self, text: str) -> tuple[str, bool]:
        """Translate Japanese text to English.

        Args:
            text: Japanese text to translate.

        Returns:
            Tuple of (translated English text, was_cached).
        """
        if not text or not text.strip():
            return "", False

        # Check cache first (includes fuzzy matching)
        cached = self._cache.get(text)
        if cached is not None:
            return cached, True

        # Use parent's translate method (which handles loading and caching)
        result = super().translate(text)

        return result, False
