"""Translation module using Sugoi V4 for offline Japanese to English."""

from difflib import SequenceMatcher

# Translation cache defaults
DEFAULT_CACHE_SIZE = 200            # Max cached translations
DEFAULT_SIMILARITY_THRESHOLD = 0.9  # Fuzzy match threshold for cache lookup


def text_similarity(a: str, b: str) -> float:
    """Calculate similarity ratio between two strings (0.0 to 1.0)."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


class TranslationCache:
    """LRU cache for translations with fuzzy key matching."""

    def __init__(
        self,
        max_size: int = DEFAULT_CACHE_SIZE,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    ):
        """Initialize the cache.

        Args:
            max_size: Maximum number of entries to store.
            similarity_threshold: Minimum similarity ratio for fuzzy match (0.0-1.0).
        """
        self._cache: dict[str, str] = {}
        self._max_size = max_size
        self._similarity_threshold = similarity_threshold

    def get(self, text: str) -> str | None:
        """Get cached translation, using fuzzy matching if exact match not found.

        Args:
            text: Japanese text to look up.

        Returns:
            Cached translation if found, None otherwise.
        """
        # Try exact match first
        if text in self._cache:
            return self._cache[text]

        # Try fuzzy match
        for cached_text, translation in self._cache.items():
            if text_similarity(text, cached_text) >= self._similarity_threshold:
                return translation

        return None

    def put(self, text: str, translation: str) -> None:
        """Store a translation in the cache.

        Args:
            text: Japanese source text.
            translation: English translation.
        """
        # Simple LRU: remove oldest entry if at capacity
        if len(self._cache) >= self._max_size and text not in self._cache:
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]

        self._cache[text] = translation


class Translator:
    """Translates Japanese text to English using Sugoi V4 (CTranslate2)."""

    def __init__(
        self,
        cache_size: int = DEFAULT_CACHE_SIZE,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    ):
        """Initialize the translator (lazy loading).

        Args:
            cache_size: Maximum number of translations to cache.
            similarity_threshold: Minimum similarity for fuzzy cache match (0.0-1.0).
        """
        self._model_path = None
        self._translator = None
        self._tokenizer = None
        self._cache = TranslationCache(cache_size, similarity_threshold)

    def load(self) -> None:
        """Load the translation model, downloading if needed."""
        if self._translator is not None:
            return

        print("Loading Sugoi V4...")

        import ctranslate2
        import sentencepiece as spm

        # Get model path (downloads from HuggingFace if needed)
        from .models import get_sugoi_model_path
        self._model_path = get_sugoi_model_path()

        # Load CTranslate2 model
        self._translator = ctranslate2.Translator(
            str(self._model_path),
            device="auto",  # Automatically use GPU if available
        )

        # Load SentencePiece tokenizer
        tokenizer_path = self._model_path / "spm" / "spm.ja.nopretok.model"
        self._tokenizer = spm.SentencePieceProcessor()
        self._tokenizer.Load(str(tokenizer_path))

        print("Sugoi V4 ready.")

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

        # Ensure model is loaded
        if self._translator is None:
            self.load()

        # Tokenize input
        tokens = self._tokenizer.EncodeAsPieces(text)

        # Translate
        results = self._translator.translate_batch(
            [tokens],
            beam_size=5,
            max_decoding_length=256,
        )

        # Decode output - join tokens and clean up SentencePiece markers
        translated_tokens = results[0].hypotheses[0]
        result = "".join(translated_tokens).replace("▁", " ").strip()

        # Store in cache
        self._cache.put(text, result)

        return result, False

    def is_loaded(self) -> bool:
        """Check if the translation model is loaded.

        Returns:
            True if model is loaded, False otherwise.
        """
        return self._translator is not None
