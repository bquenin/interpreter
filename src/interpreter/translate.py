"""Translation module for offline Japanese and Chinese to English."""

import os
import sys
from difflib import SequenceMatcher
from pathlib import Path

# Suppress HuggingFace Hub warnings (must be set before import)
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
os.environ["HF_HUB_VERBOSITY"] = "error"

from . import log
from .config import SourceLanguage
from .models import ModelLoadError

logger = log.get_logger()

SUGOI_REPO_ID = "entai2965/sugoi-v4-ja-en-ctranslate2"
OPUS_ZH_EN_REPO_ID = "gaudi/opus-mt-zh-en-ctranslate2"

REQUIRED_MODEL_FILES = [
    "model.bin",
    "spm/spm.ja.nopretok.model",
]

DEFAULT_CACHE_SIZE = 200
DEFAULT_SIMILARITY_THRESHOLD = 0.9


def _snapshot_download(*args, **kwargs):
    from huggingface_hub import snapshot_download

    return snapshot_download(*args, **kwargs)


def _get_local_entry_not_found_error():
    from huggingface_hub.utils import LocalEntryNotFoundError

    return LocalEntryNotFoundError


def _get_short_path(path: Path) -> str:
    """Convert path to Windows short (8.3) format to handle non-ASCII characters."""
    if sys.platform == "win32":
        import ctypes

        buf = ctypes.create_unicode_buffer(512)
        if ctypes.windll.kernel32.GetShortPathNameW(str(path), buf, 512):
            return buf.value
    return str(path)


def _validate_model_files(model_path: Path, required_files: list[str]) -> bool:
    for file_path in required_files:
        if not (model_path / file_path).exists():
            logger.warning("missing model file", file=file_path)
            return False
    return True


def _get_model_path(repo_id: str, required_files: list[str], download_size: str | None = None) -> Path:
    """Get path to a Hugging Face model, downloading if needed."""
    local_entry_not_found_error = _get_local_entry_not_found_error()

    try:
        model_path = _snapshot_download(repo_id=repo_id, local_files_only=True)
        model_path = Path(model_path)
        if _validate_model_files(model_path, required_files):
            return model_path
        raise ModelLoadError("Model cache is corrupted. Click 'Fix Models' to repair.")
    except local_entry_not_found_error:
        pass

    log_fields = {"repo": repo_id}
    if download_size:
        log_fields["size"] = download_size
    logger.info("downloading translation model", **log_fields)
    model_path = Path(_snapshot_download(repo_id=repo_id))

    if not _validate_model_files(model_path, required_files):
        raise ModelLoadError("Translation model download incomplete. Click 'Fix Models' to retry.")

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
        self._cache: dict[str, str] = {}
        self._max_size = max_size
        self._similarity_threshold = similarity_threshold

    def get(self, text: str) -> str | None:
        if text in self._cache:
            return self._cache[text]

        for cached_text, translation in self._cache.items():
            if text_similarity(text, cached_text) >= self._similarity_threshold:
                return translation

        return None

    def put(self, text: str, translation: str) -> None:
        if len(self._cache) >= self._max_size and text not in self._cache:
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]

        self._cache[text] = translation


class JapaneseTranslator:
    """Translates Japanese text to English using Sugoi V4 (CTranslate2)."""

    def __init__(
        self,
        cache_size: int = DEFAULT_CACHE_SIZE,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    ):
        self._model_path = None
        self._translator = None
        self._tokenizer = None
        self._cache = TranslationCache(cache_size, similarity_threshold)

    def load(self) -> None:
        if self._translator is not None:
            return

        logger.info("loading sugoi v4")

        import ctranslate2
        import sentencepiece as spm

        self._model_path = _get_model_path(SUGOI_REPO_ID, REQUIRED_MODEL_FILES, download_size="~1.1GB")

        device = "cpu"
        try:
            cuda_types = ctranslate2.get_supported_compute_types("cuda")
            if cuda_types:
                self._translator = ctranslate2.Translator(_get_short_path(self._model_path), device="cuda")
                self._translator.translate_batch([["テスト"]])
                device = "cuda"
        except Exception as e:
            logger.debug("CUDA failed, falling back to CPU", error=str(e))

        if device == "cpu":
            self._translator = ctranslate2.Translator(_get_short_path(self._model_path), device="cpu")

        tokenizer_path = self._model_path / "spm" / "spm.ja.nopretok.model"
        self._tokenizer = spm.SentencePieceProcessor(model_proto=tokenizer_path.read_bytes())

        logger.info("sugoi v4 ready", device=("GPU" if device == "cuda" else "CPU"))

    def translate(self, text: str) -> tuple[str, bool]:
        if not text or not text.strip():
            return "", False

        cached = self._cache.get(text)
        if cached is not None:
            return cached, True

        if self._translator is None:
            self.load()

        tokens = self._tokenizer.EncodeAsPieces(text)
        results = self._translator.translate_batch([tokens], beam_size=5, max_decoding_length=256)
        translated_tokens = results[0].hypotheses[0]
        result = "".join(translated_tokens).replace("▁", " ").strip()
        result = normalize_translation_text(result)
        self._cache.put(text, result)
        return result, False

    def is_loaded(self) -> bool:
        return self._translator is not None


class ChineseTranslator:
    """Translates Chinese text to English using OPUS-MT (CTranslate2)."""

    def __init__(
        self,
        cache_size: int = DEFAULT_CACHE_SIZE,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    ):
        self._model_path = None
        self._translator = None
        self._tokenizer = None
        self._cache = TranslationCache(cache_size, similarity_threshold)

    def load(self) -> None:
        if self._translator is not None:
            return

        logger.info("loading opus zh-en")

        import ctranslate2
        from transformers import AutoTokenizer

        required_files = ["model.bin", "source.spm", "target.spm"]
        self._model_path = _get_model_path(OPUS_ZH_EN_REPO_ID, required_files, download_size="~155MB")

        device = "cpu"
        try:
            cuda_types = ctranslate2.get_supported_compute_types("cuda")
            if cuda_types:
                self._translator = ctranslate2.Translator(str(self._model_path), device="cuda")
                self._translator.translate_batch([["▁测试", "</s>"]])
                device = "cuda"
        except Exception as e:
            logger.debug("CUDA failed, falling back to CPU", error=str(e))

        if device == "cpu":
            self._translator = ctranslate2.Translator(str(self._model_path), device="cpu")

        self._tokenizer = AutoTokenizer.from_pretrained(self._model_path)
        logger.info("opus zh-en ready", device=("GPU" if device == "cuda" else "CPU"))

    def translate(self, text: str) -> tuple[str, bool]:
        if not text or not text.strip():
            return "", False

        cached = self._cache.get(text)
        if cached is not None:
            return cached, True

        if self._translator is None:
            self.load()

        input_ids = self._tokenizer.encode(text)
        tokens = self._tokenizer.convert_ids_to_tokens(input_ids)
        results = self._translator.translate_batch([tokens], beam_size=4, max_decoding_length=256)
        translated_tokens = results[0].hypotheses[0]
        translated_ids = self._tokenizer.convert_tokens_to_ids(translated_tokens)
        result = self._tokenizer.decode(translated_ids, skip_special_tokens=True).strip()
        result = normalize_translation_text(result)
        self._cache.put(text, result)
        return result, False

    def is_loaded(self) -> bool:
        return self._translator is not None


def normalize_translation_text(result: str) -> str:
    return (
        result
        .replace("‘", "'")
        .replace("’", "'")
        .replace("“", '"')
        .replace("”", '"')
        .replace("–", "-")
        .replace("—", "--")
        .replace("−", "-")
        .replace(" ", " ")
        .replace("…", "...")
    )


class Translator:
    """Language-aware translation wrapper."""

    def __init__(
        self,
        source_language: SourceLanguage = SourceLanguage.JAPANESE,
        cache_size: int = DEFAULT_CACHE_SIZE,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    ):
        if source_language == SourceLanguage.CHINESE:
            self._backend = ChineseTranslator(cache_size, similarity_threshold)
        else:
            self._backend = JapaneseTranslator(cache_size, similarity_threshold)

    def load(self) -> None:
        self._backend.load()

    def translate(self, text: str) -> tuple[str, bool]:
        return self._backend.translate(text)

    def is_loaded(self) -> bool:
        return self._backend.is_loaded()


def get_translation_repo_id(source_language: SourceLanguage) -> str:
    if source_language == SourceLanguage.CHINESE:
        return OPUS_ZH_EN_REPO_ID
    return SUGOI_REPO_ID
