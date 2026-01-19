"""Translation backend implementations."""

from .opus_mt import OpusMTTranslationBackend
from .sugoi import SugoiTranslationBackend

__all__ = [
    "SugoiTranslationBackend",
    "OpusMTTranslationBackend",
]
