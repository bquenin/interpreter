"""OPUS-MT translation backend for multiple language pairs."""

import os
import sys

# Suppress HuggingFace Hub warnings (must be set before import)
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
os.environ["HF_HUB_VERBOSITY"] = "error"

from pathlib import Path

from huggingface_hub import snapshot_download
from huggingface_hub.utils import LocalEntryNotFoundError

from ... import log
from ...models import ModelLoadError
from ..base import Language, TranslationBackend, TranslationBackendInfo

logger = log.get_logger()

# Helsinki-NLP OPUS-MT models on HuggingFace
# Format: (source, target) -> repo_id
# License: CC-BY 4.0 / Apache 2.0 (permissive, attribution required)
OPUS_MT_MODELS = {
    # Japanese to other languages
    # Note: JA->EN exists but Sugoi is preferred for game/manga text
    (Language.JAPANESE, Language.ENGLISH): "Helsinki-NLP/opus-mt-ja-en",
    (Language.JAPANESE, Language.FRENCH): "Helsinki-NLP/opus-mt-ja-fr",
    (Language.JAPANESE, Language.GERMAN): "Helsinki-NLP/opus-mt-ja-de",
    (Language.JAPANESE, Language.SPANISH): "Helsinki-NLP/opus-mt-ja-es",
    (Language.JAPANESE, Language.ITALIAN): "Helsinki-NLP/opus-mt-ja-it",
    (Language.JAPANESE, Language.PORTUGUESE): "Helsinki-NLP/opus-mt-ja-pt",
    (Language.JAPANESE, Language.DUTCH): "Helsinki-NLP/opus-mt-ja-nl",
    (Language.JAPANESE, Language.POLISH): "Helsinki-NLP/opus-mt-ja-pl",
    (Language.JAPANESE, Language.RUSSIAN): "Helsinki-NLP/opus-mt-ja-ru",
    # English to other languages
    (Language.ENGLISH, Language.FRENCH): "Helsinki-NLP/opus-mt-en-fr",
    (Language.ENGLISH, Language.GERMAN): "Helsinki-NLP/opus-mt-en-de",
    (Language.ENGLISH, Language.SPANISH): "Helsinki-NLP/opus-mt-en-es",
    (Language.ENGLISH, Language.ITALIAN): "Helsinki-NLP/opus-mt-en-it",
    (Language.ENGLISH, Language.PORTUGUESE): "Helsinki-NLP/opus-mt-en-pt",
    (Language.ENGLISH, Language.DUTCH): "Helsinki-NLP/opus-mt-en-nl",
    (Language.ENGLISH, Language.POLISH): "Helsinki-NLP/opus-mt-en-pl",
    (Language.ENGLISH, Language.RUSSIAN): "Helsinki-NLP/opus-mt-en-ru",
    # Other languages to English
    (Language.FRENCH, Language.ENGLISH): "Helsinki-NLP/opus-mt-fr-en",
    (Language.GERMAN, Language.ENGLISH): "Helsinki-NLP/opus-mt-de-en",
    (Language.SPANISH, Language.ENGLISH): "Helsinki-NLP/opus-mt-es-en",
    (Language.ITALIAN, Language.ENGLISH): "Helsinki-NLP/opus-mt-it-en",
    (Language.PORTUGUESE, Language.ENGLISH): "Helsinki-NLP/opus-mt-pt-en",
    (Language.DUTCH, Language.ENGLISH): "Helsinki-NLP/opus-mt-nl-en",
    (Language.POLISH, Language.ENGLISH): "Helsinki-NLP/opus-mt-pl-en",
    (Language.RUSSIAN, Language.ENGLISH): "Helsinki-NLP/opus-mt-ru-en",
}

# Model size in MB (approximate, varies slightly by language pair)
OPUS_MT_MODEL_SIZE_MB = 300


def _get_short_path(path: Path) -> str:
    """Convert path to Windows short (8.3) format to handle non-ASCII characters."""
    if sys.platform == "win32":
        import ctypes

        buf = ctypes.create_unicode_buffer(512)
        if ctypes.windll.kernel32.GetShortPathNameW(str(path), buf, 512):
            return buf.value
    return str(path)


class OpusMTTranslationBackend(TranslationBackend):
    """Translates text using Helsinki-NLP OPUS-MT models.

    OPUS-MT provides high-quality translation for many language pairs
    under a permissive Apache 2.0 license. Models use the same CTranslate2
    inference engine as Sugoi for consistent performance.
    """

    def __init__(self, source_language: Language, target_language: Language):
        """Initialize the OPUS-MT translator.

        Args:
            source_language: Source language for translation.
            target_language: Target language for translation.

        Raises:
            ValueError: If the language pair is not supported.
        """
        self._source = source_language
        self._target = target_language
        self._pair = (source_language, target_language)

        if self._pair not in OPUS_MT_MODELS:
            raise ValueError(
                f"Language pair {source_language.value} -> {target_language.value} "
                f"is not supported by OPUS-MT backend"
            )

        self._repo_id = OPUS_MT_MODELS[self._pair]
        self._model_path = None
        self._translator = None
        self._tokenizer = None

    @classmethod
    def get_info(cls) -> TranslationBackendInfo:
        """Get metadata about this backend.

        Note: This returns generic info. For specific language pair info,
        use get_info_for_pair().
        """
        return TranslationBackendInfo(
            id="opus_mt",
            name="OPUS-MT",
            source_language=Language.ENGLISH,
            target_language=Language.FRENCH,
            model_size_mb=OPUS_MT_MODEL_SIZE_MB,
            license="Apache-2.0",
            description="Helsinki-NLP machine translation models",
            is_default=False,
            huggingface_repo="Helsinki-NLP/opus-mt-en-fr",
        )

    @classmethod
    def get_info_for_pair(cls, source: Language, target: Language) -> TranslationBackendInfo:
        """Get metadata for a specific language pair.

        Args:
            source: Source language.
            target: Target language.

        Returns:
            TranslationBackendInfo for this language pair.

        Raises:
            ValueError: If the language pair is not supported.
        """
        pair = (source, target)
        if pair not in OPUS_MT_MODELS:
            raise ValueError(f"Language pair {source.value} -> {target.value} not supported")

        repo_id = OPUS_MT_MODELS[pair]

        # JA->EN is not default (Sugoi is), all others are default
        is_default = pair != (Language.JAPANESE, Language.ENGLISH)

        return TranslationBackendInfo(
            id=f"opus_mt_{source.value}_{target.value}",
            name=f"OPUS-MT ({source.value.upper()}→{target.value.upper()})",
            source_language=source,
            target_language=target,
            model_size_mb=OPUS_MT_MODEL_SIZE_MB,
            license="Apache-2.0",
            description=f"Helsinki-NLP {source.display_name} to {target.display_name} translation",
            is_default=is_default,
            huggingface_repo=repo_id,
        )

    @classmethod
    def get_supported_pairs(cls) -> list[tuple[Language, Language]]:
        """Get all supported language pairs.

        Returns:
            List of (source, target) language tuples.
        """
        return list(OPUS_MT_MODELS.keys())

    def _get_model_path(self) -> Path:
        """Get path to OPUS-MT model, downloading if needed.

        Returns:
            Path to the model directory.

        Raises:
            ModelLoadError: If model files are missing or corrupted.
        """
        # First try to load from cache (no network request)
        try:
            model_path = snapshot_download(
                repo_id=self._repo_id,
                local_files_only=True,
            )
            return Path(model_path)
        except LocalEntryNotFoundError:
            pass

        # Not cached, download from HuggingFace
        logger.info("downloading opus-mt model", repo=self._repo_id, size=f"~{OPUS_MT_MODEL_SIZE_MB}MB")
        model_path = Path(snapshot_download(repo_id=self._repo_id))

        return model_path

    def load(self) -> None:
        """Load the translation model, downloading if needed.

        Raises:
            ModelLoadError: If model fails to load.
        """
        if self._translator is not None:
            return

        logger.info("loading opus-mt", pair=f"{self._source.value}->{self._target.value}")

        from transformers import MarianTokenizer

        # Get model path (downloads from HuggingFace if needed)
        self._model_path = self._get_model_path()

        # Use transformers for OPUS-MT models
        # CTranslate2 conversion is complex and varies by model version,
        # so we use transformers directly which is more reliable
        self._load_transformers()

    def _load_ctranslate2(self) -> None:
        """Load model using CTranslate2 for faster inference."""
        import ctranslate2

        # Check if CTranslate2 converted model exists
        ct2_path = self._model_path / "ctranslate2"
        if not ct2_path.exists():
            # Convert model to CTranslate2 format
            self._convert_to_ctranslate2()

        # Load CTranslate2 model
        device = "cpu"
        try:
            cuda_types = ctranslate2.get_supported_compute_types("cuda")
            if cuda_types:
                self._translator = ctranslate2.Translator(
                    _get_short_path(ct2_path),
                    device="cuda",
                )
                device = "cuda"
        except Exception:
            pass

        if device == "cpu":
            self._translator = ctranslate2.Translator(
                _get_short_path(ct2_path),
                device="cpu",
            )

        # Load tokenizer
        from transformers import MarianTokenizer

        self._tokenizer = MarianTokenizer.from_pretrained(str(self._model_path))
        self._use_ctranslate2 = True

        device_info = "GPU" if device == "cuda" else "CPU"
        logger.info("opus-mt ready (ctranslate2)", device=device_info)

    def _convert_to_ctranslate2(self) -> None:
        """Convert Marian model to CTranslate2 format."""
        import ctranslate2

        ct2_path = self._model_path / "ctranslate2"
        logger.info("converting opus-mt to ctranslate2 format")

        # MarianConverter requires model_dir and vocab_paths for source/target tokenizers
        # For OPUS-MT models, both source and target use the same vocab file
        vocab_file = self._model_path / "vocab.json"
        source_spm = self._model_path / "source.spm"
        target_spm = self._model_path / "target.spm"

        converter = ctranslate2.converters.MarianConverter(
            str(self._model_path),
            [str(source_spm), str(target_spm)] if source_spm.exists() else [str(vocab_file)],
        )
        converter.convert(
            str(ct2_path),
            quantization="int8",  # Use int8 quantization for smaller size
        )

    def _load_transformers(self) -> None:
        """Load model using transformers (slower but always works)."""
        from transformers import MarianMTModel, MarianTokenizer

        self._tokenizer = MarianTokenizer.from_pretrained(str(self._model_path))
        self._translator = MarianMTModel.from_pretrained(str(self._model_path))
        self._use_ctranslate2 = False

        logger.info("opus-mt ready (transformers)")

    def translate(self, text: str) -> str:
        """Translate text.

        Args:
            text: Source text to translate.

        Returns:
            Translated text.
        """
        if not text or not text.strip():
            return ""

        # Ensure model is loaded
        if self._translator is None:
            self.load()

        if self._use_ctranslate2:
            return self._translate_ctranslate2(text)
        else:
            return self._translate_transformers(text)

    def _translate_ctranslate2(self, text: str) -> str:
        """Translate using CTranslate2."""
        # Tokenize
        tokens = self._tokenizer.tokenize(text)

        # Translate
        results = self._translator.translate_batch(
            [tokens],
            beam_size=5,
            max_decoding_length=256,
        )

        # Decode
        translated_tokens = results[0].hypotheses[0]
        result = self._tokenizer.convert_tokens_to_string(translated_tokens)

        return result.strip()

    def _translate_transformers(self, text: str) -> str:
        """Translate using transformers."""
        # Tokenize
        inputs = self._tokenizer(text, return_tensors="pt", padding=True, truncation=True)

        # Translate
        outputs = self._translator.generate(**inputs, max_length=256, num_beams=5)

        # Decode
        result = self._tokenizer.decode(outputs[0], skip_special_tokens=True)

        return result.strip()

    def is_loaded(self) -> bool:
        """Check if the translation model is loaded."""
        return self._translator is not None
