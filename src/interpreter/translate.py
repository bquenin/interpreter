"""Translation module using Sugoi V4 for offline Japanese to English."""

import os
import sys

# Suppress HuggingFace Hub warnings (must be set before import)
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
os.environ["HF_HUB_VERBOSITY"] = "error"

from difflib import SequenceMatcher
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from huggingface_hub import snapshot_download
from huggingface_hub.utils import LocalEntryNotFoundError

from . import log
from .models import ModelLoadError

if TYPE_CHECKING:
    from .config import Config

logger = log.get_logger()

# Official HuggingFace repository for Sugoi V4, pinned to a specific commit so the
# file layout we rely on (model.bin, config.json, vocabularies, spm/) cannot change
# underneath us. Bump deliberately when upgrading the model.
SUGOI_REPO_ID = "entai2965/sugoi-v4-ja-en-ctranslate2"
SUGOI_REVISION = "71d67eb8e73ec2f5aaefc0689e03a4eb843d3a2b"

# Attempts for the online download; snapshot_download resumes where it left off.
DOWNLOAD_ATTEMPTS = 3

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


def _download_sugoi_model() -> Path:
    """Download the Sugoi V4 snapshot from HuggingFace, or complete a partial one.

    snapshot_download compares the local cache against the repository's file list
    and only fetches what is missing, so this also repairs a cache left incomplete
    by an interrupted download. Transient failures are retried; the download resumes.

    Returns:
        Path to the model directory.

    Raises:
        ModelLoadError: If the download keeps failing.
    """
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        try:
            return Path(snapshot_download(repo_id=SUGOI_REPO_ID, revision=SUGOI_REVISION))
        except Exception as e:
            if attempt == DOWNLOAD_ATTEMPTS:
                raise ModelLoadError(
                    f"Translation model download failed: {e}. Check your connection and click 'Fix Models' to retry."
                ) from e
            logger.warning("model download failed, retrying", attempt=attempt, error=str(e))
    raise AssertionError("unreachable")  # pragma: no cover


def _get_sugoi_model_path() -> Path:
    """Get path to the Sugoi V4 snapshot, downloading it on first use.

    A cached snapshot is returned without any network access. Whether it is
    complete is only known once CTranslate2 loads it (see Translator.load),
    which avoids hardcoding the repository's file layout here.

    Returns:
        Path to the model directory.

    Raises:
        ModelLoadError: If the model cannot be downloaded.
    """
    try:
        return Path(
            snapshot_download(
                repo_id=SUGOI_REPO_ID,
                revision=SUGOI_REVISION,
                local_files_only=True,
            )
        )
    except LocalEntryNotFoundError:
        logger.info("downloading sugoi v4 model", size="~1.1GB")
        return _download_sugoi_model()


def text_similarity(a: str, b: str) -> float:
    """Calculate similarity ratio between two strings (0.0 to 1.0)."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def normalize_output(text: str) -> str:
    """Normalize Unicode punctuation to ASCII equivalents (fixes overlay rendering issues)."""
    return (
        text.strip()
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


class TranslationEngine(Protocol):
    """Interface shared by the built-in Sugoi translator and the LLM endpoint backend."""

    @property
    def name(self) -> str:
        """Short description for the status panel (e.g. "Sugoi V4")."""
        ...

    def load(self) -> None:
        """Load or connect the engine. Raises ModelLoadError on failure."""
        ...

    def translate(self, text: str) -> tuple[str, bool]:
        """Translate Japanese text. Returns (translation, was_cached)."""
        ...

    def is_loaded(self) -> bool: ...


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

    @property
    def name(self) -> str:
        """Short description for the status panel."""
        return "Sugoi V4"

    def load(self) -> None:
        """Load the translation model, downloading if needed.

        Raises:
            ModelLoadError: If model fails to load.
        """
        if self._translator is not None:
            return

        logger.info("loading sugoi v4")

        # Get model path (downloads from HuggingFace if needed)
        self._model_path = _get_sugoi_model_path()

        # Only RuntimeError (CTranslate2/SentencePiece rejecting the files) and
        # FileNotFoundError indicate an incomplete cache. Other OSErrors such as
        # PermissionError are local problems a re-download cannot fix, so they
        # propagate unchanged.
        try:
            self._load_from_path()
        except (RuntimeError, FileNotFoundError) as e:
            # An interrupted download can leave a snapshot with model.bin but without
            # config.json or the vocabularies, which CTranslate2 reports as an opaque
            # JSON error. Re-sync the snapshot with the Hub (only missing files are
            # fetched) and retry once before giving up.
            logger.warning("translation model failed to load, repairing cache", error=str(e))
            self._model_path = _download_sugoi_model()
            try:
                self._load_from_path()
            except (RuntimeError, FileNotFoundError) as retry_error:
                raise ModelLoadError(
                    f"Translation model is corrupted ({retry_error}). Click 'Fix Models' to repair."
                ) from retry_error

    def _load_from_path(self) -> None:
        """Load CTranslate2 model and tokenizer from self._model_path.

        Instance state is only updated once both components loaded, so a failure
        never leaves the translator half-initialized (load() would otherwise
        return early on the next attempt).

        Raises:
            RuntimeError: If CTranslate2 or SentencePiece reject the model files.
            OSError: If a model file is missing or unreadable.
        """
        import ctranslate2
        import sentencepiece as spm

        # Load CTranslate2 model with GPU if available, fallback to CPU
        device = "cpu"
        try:
            cuda_types = ctranslate2.get_supported_compute_types("cuda")
            if cuda_types:
                # Try to load with GPU
                translator = ctranslate2.Translator(
                    _get_short_path(self._model_path),
                    device="cuda",
                )
                # Test inference to verify CUDA actually works
                # (loading may succeed but inference can fail if cuBLAS is missing)
                translator.translate_batch([["テスト"]])
                device = "cuda"
        except Exception as e:
            # GPU failed (load or inference), will use CPU below
            logger.debug("CUDA failed, falling back to CPU", error=str(e))

        if device == "cpu":
            translator = ctranslate2.Translator(
                _get_short_path(self._model_path),
                device="cpu",
            )

        # Load SentencePiece tokenizer
        # Read model as bytes to avoid Unicode path issues on Windows
        # (SentencePiece's C++ layer may not handle non-ASCII paths correctly)
        tokenizer_path = self._model_path / "spm" / "spm.ja.nopretok.model"
        tokenizer = spm.SentencePieceProcessor(model_proto=tokenizer_path.read_bytes())

        self._translator = translator
        self._tokenizer = tokenizer

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

        result = normalize_output(result)

        # Store in cache
        self._cache.put(text, result)

        return result, False

    def is_loaded(self) -> bool:
        """Check if the translation model is loaded.

        Returns:
            True if model is loaded, False otherwise.
        """
        return self._translator is not None


SUGOI_SOURCE_LANGUAGE = "Japanese"
SUGOI_ONLY_JAPANESE = (
    "Sugoi V4 only translates Japanese. Set the source language to Japanese or pick the LLM endpoint engine."
)


def create_translator(config: "Config") -> TranslationEngine:
    """Build the translation engine selected in the configuration.

    Raises:
        ModelLoadError: If the built-in engine cannot handle the configured source language.
    """
    from .config import TranslationBackend

    if config.translation_backend == TranslationBackend.LLM:
        from .llm_translate import LLMTranslator

        return LLMTranslator(config.llm, source_language=config.source_language)
    if config.source_language != SUGOI_SOURCE_LANGUAGE:
        from .models import ModelLoadError

        raise ModelLoadError(SUGOI_ONLY_JAPANESE)
    return Translator()
