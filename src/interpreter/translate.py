"""Translation module using Sugoi V4 for offline Japanese to English."""

import os
import sys

# Suppress HuggingFace Hub warnings (must be set before import)
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
os.environ["HF_HUB_VERBOSITY"] = "error"

from difflib import SequenceMatcher
from pathlib import Path

from huggingface_hub import snapshot_download
from huggingface_hub.utils import LocalEntryNotFoundError

from . import log
from .models import ModelLoadError

logger = log.get_logger()

# Official HuggingFace repository for Sugoi V4
SUGOI_REPO_ID = "entai2965/sugoi-v4-ja-en-ctranslate2"

# Required files that must exist for the model to work
REQUIRED_MODEL_FILES = [
    "model.bin",
    "spm/spm.ja.nopretok.model",
]

# Translation cache defaults
DEFAULT_CACHE_SIZE = 200  # Max cached translations
DEFAULT_SIMILARITY_THRESHOLD = 0.9  # Fuzzy match threshold for cache lookup


def _get_short_path(path: Path) -> str:
    """Convert path to Windows short (8.3) format to handle non-ASCII characters.

    CTranslate2 and SentencePiece (C++ libraries) may fail to load files from paths
    containing non-ASCII characters on Windows. This function converts paths to the
    short 8.3 format which only uses ASCII characters.

    Args:
        path: Path to convert.

    Returns:
        Short path string on Windows if conversion succeeds, otherwise original path string.
    """
    if sys.platform == "win32":
        import ctypes

        buf = ctypes.create_unicode_buffer(512)
        if ctypes.windll.kernel32.GetShortPathNameW(str(path), buf, 512):
            return buf.value
    return str(path)


def _validate_model_files(model_path: Path) -> bool:
    """Check if all required model files exist.

    Args:
        model_path: Path to the model directory.

    Returns:
        True if all required files exist, False otherwise.
    """
    for file_path in REQUIRED_MODEL_FILES:
        if not (model_path / file_path).exists():
            logger.warning("missing model file", file=file_path)
            return False
    return True


def _get_sugoi_model_path() -> Path:
    """Get path to Sugoi V4 translation model, downloading if needed.

    Downloads from official HuggingFace source on first use.
    Model is cached in standard HuggingFace cache (~/.cache/huggingface/).

    Returns:
        Path to the model directory.

    Raises:
        ModelLoadError: If model files are missing or corrupted.
    """
    # First try to load from cache (no network request)
    try:
        model_path = snapshot_download(
            repo_id=SUGOI_REPO_ID,
            local_files_only=True,
        )
        model_path = Path(model_path)
        # Validate that required files exist
        if _validate_model_files(model_path):
            return model_path
        # Files missing - raise error (UI will show "Fix Models" button)
        raise ModelLoadError(
            "Translation model cache is corrupted. Click 'Fix Models' to repair."
        )
    except LocalEntryNotFoundError:
        pass

    # Not cached, download from HuggingFace
    logger.info("downloading sugoi v4 model", size="~1.1GB")
    model_path = Path(snapshot_download(repo_id=SUGOI_REPO_ID))

    # Validate download completed successfully
    if not _validate_model_files(model_path):
        raise ModelLoadError(
            "Translation model download incomplete. Click 'Fix Models' to retry."
        )

    return model_path


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
        """Load the translation model, downloading if needed.

        Raises:
            ModelLoadError: If model fails to load.
        """
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
                    _get_short_path(self._model_path),
                    device="cuda",
                )
                # Test inference to verify CUDA actually works
                # (loading may succeed but inference can fail if cuBLAS is missing)
                self._translator.translate_batch([["テスト"]])
                device = "cuda"
        except Exception as e:
            # GPU failed (load or inference), will use CPU below
            logger.debug("CUDA failed, falling back to CPU", error=str(e))

        if device == "cpu":
            self._translator = ctranslate2.Translator(
                _get_short_path(self._model_path),
                device="cpu",
            )

        # Load SentencePiece tokenizer
        # Read model as bytes to avoid Unicode path issues on Windows
        # (SentencePiece's C++ layer may not handle non-ASCII paths correctly)
        tokenizer_path = self._model_path / "spm" / "spm.ja.nopretok.model"
        self._tokenizer = spm.SentencePieceProcessor(model_proto=tokenizer_path.read_bytes())

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
            .replace("\u2018", "'")  # LEFT SINGLE QUOTATION MARK
            .replace("\u2019", "'")  # RIGHT SINGLE QUOTATION MARK
            .replace("\u201c", '"')  # LEFT DOUBLE QUOTATION MARK
            .replace("\u201d", '"')  # RIGHT DOUBLE QUOTATION MARK
            # Dashes
            .replace("\u2013", "-")  # EN DASH
            .replace("\u2014", "--")  # EM DASH
            .replace("\u2212", "-")  # MINUS SIGN
            # Spaces
            .replace("\u00a0", " ")  # NO-BREAK SPACE
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
