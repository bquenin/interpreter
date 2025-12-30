"""Translation module using Sugoi V4 for offline Japanese to English."""

from pathlib import Path


class Translator:
    """Translates Japanese text to English using Sugoi V4 (CTranslate2)."""

    def __init__(self):
        """Initialize the translator (lazy loading)."""
        self._model_path: Path | None = None
        self._translator = None
        self._tokenizer = None

    def load(self) -> None:
        """Load the translation model, downloading if needed."""
        if self._translator is not None:
            return

        import ctranslate2
        import sentencepiece as spm

        # Get model path (downloads from HuggingFace if needed)
        from .models import get_sugoi_model_path
        self._model_path = get_sugoi_model_path()

        print(f"Loading Sugoi V4 translator from {self._model_path}...")

        # Load CTranslate2 model
        self._translator = ctranslate2.Translator(
            str(self._model_path),
            device="auto",  # Automatically use GPU if available
        )

        # Load SentencePiece tokenizer
        tokenizer_path = self._model_path / "spm" / "spm.ja.nopretok.model"
        self._tokenizer = spm.SentencePieceProcessor()
        self._tokenizer.Load(str(tokenizer_path))

        print("Translator ready.")

    def translate(self, text: str) -> str:
        """Translate Japanese text to English.

        Args:
            text: Japanese text to translate.

        Returns:
            Translated English text.
        """
        if not text or not text.strip():
            return ""

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

        return result

    def is_loaded(self) -> bool:
        """Check if the translation model is loaded.

        Returns:
            True if model is loaded, False otherwise.
        """
        return self._translator is not None
