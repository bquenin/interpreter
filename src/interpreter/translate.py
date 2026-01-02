"""Translation module using Sugoi V4 for offline Japanese to English."""

import os
from difflib import SequenceMatcher
from pathlib import Path

from huggingface_hub import snapshot_download
from huggingface_hub.utils import LocalEntryNotFoundError

from . import log

logger = log.get_logger()

# Suppress HuggingFace Hub warning about unauthenticated requests
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"

# Official HuggingFace repository for Sugoi V4
SUGOI_REPO_ID = "entai2965/sugoi-v4-ja-en-ctranslate2"

# Translation cache defaults
DEFAULT_CACHE_SIZE = 200            # Max cached translations
DEFAULT_SIMILARITY_THRESHOLD = 0.9  # Fuzzy match threshold for cache lookup


def _get_sugoi_model_path() -> Path:
    """Get path to Sugoi V4 translation model, downloading if needed.

    Downloads from official HuggingFace source on first use.
    Model is cached in standard HuggingFace cache (~/.cache/huggingface/).

    Returns:
        Path to the model directory.
    """
    # First try to load from cache (no network request)
    try:
        model_path = snapshot_download(
            repo_id=SUGOI_REPO_ID,
            local_files_only=True,
        )
        return Path(model_path)
    except LocalEntryNotFoundError:
        pass

    # Not cached, download from HuggingFace
    logger.info("downloading sugoi v4 model", size="~1.1GB")
    model_path = snapshot_download(repo_id=SUGOI_REPO_ID)
    return Path(model_path)


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

        logger.info("loading sugoi v4")

        import ctranslate2
        import sentencepiece as spm

        # Get model path (downloads from HuggingFace if needed)
        self._model_path = _get_sugoi_model_path()

        # Load CTranslate2 model with GPU if available, fallback to CPU
        device = "cpu"
        try:
            cuda_types = ctranslate2.get_supported_compute_types("cuda")
            if cuda_types:
                # Try to load with GPU
                self._translator = ctranslate2.Translator(
                    str(self._model_path),
                    device="cuda",
                )
                device = "cuda"
        except Exception:
            # GPU failed, will use CPU below
            pass

        if device == "cpu":
            self._translator = ctranslate2.Translator(
                str(self._model_path),
                device="cpu",
            )

        # Load SentencePiece tokenizer
        tokenizer_path = self._model_path / "spm" / "spm.ja.nopretok.model"
        self._tokenizer = spm.SentencePieceProcessor()
        self._tokenizer.Load(str(tokenizer_path))

        device_info = "GPU" if device == "cuda" else "CPU"
        logger.info("sugoi v4 ready", device=device_info)

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

        # Normalize Unicode characters to ASCII equivalents (fixes rendering issues)
        result = (
            result
            # Curly quotes → straight quotes
            .replace("\u2018", "'")   # LEFT SINGLE QUOTATION MARK
            .replace("\u2019", "'")   # RIGHT SINGLE QUOTATION MARK
            .replace("\u201C", '"')   # LEFT DOUBLE QUOTATION MARK
            .replace("\u201D", '"')   # RIGHT DOUBLE QUOTATION MARK
            # Dashes
            .replace("\u2013", "-")   # EN DASH
            .replace("\u2014", "--")  # EM DASH
            .replace("\u2212", "-")   # MINUS SIGN
            # Spaces
            .replace("\u00A0", " ")   # NO-BREAK SPACE
            # Ellipsis
            .replace("\u2026", "...")  # HORIZONTAL ELLIPSIS
        )

        # Store in cache
        self._cache.put(text, result)

        return result, False

    def is_loaded(self) -> bool:
        """Check if the translation model is loaded.

        Returns:
            True if model is loaded, False otherwise.
        """
        return self._translator is not None
