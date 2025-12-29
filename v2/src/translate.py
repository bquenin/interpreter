"""Translation module using Argos Translate for offline Japanese to English."""

from typing import Optional


class Translator:
    """Translates Japanese text to English using Argos Translate."""

    def __init__(self, source_lang: str = "ja", target_lang: str = "en"):
        """Initialize the translator.

        Args:
            source_lang: Source language code (default: "ja" for Japanese).
            target_lang: Target language code (default: "en" for English).
        """
        self.source_lang = source_lang
        self.target_lang = target_lang
        self._translator = None

    def _ensure_model(self):
        """Lazily load the translation model on first use."""
        if self._translator is not None:
            return

        import argostranslate.package
        import argostranslate.translate

        print(f"Setting up Argos Translate ({self.source_lang} -> {self.target_lang})...")

        # Update package index
        argostranslate.package.update_package_index()

        # Get available packages
        available_packages = argostranslate.package.get_available_packages()

        # Find the package for our language pair
        package_to_install = None
        for pkg in available_packages:
            if pkg.from_code == self.source_lang and pkg.to_code == self.target_lang:
                package_to_install = pkg
                break

        if package_to_install is None:
            raise RuntimeError(
                f"No translation package found for {self.source_lang} -> {self.target_lang}. "
                "Available packages may need to be downloaded."
            )

        # Check if already installed
        installed_packages = argostranslate.package.get_installed_packages()
        is_installed = any(
            pkg.from_code == self.source_lang and pkg.to_code == self.target_lang
            for pkg in installed_packages
        )

        if not is_installed:
            print(f"Downloading translation model (this may take a moment)...")
            download_path = package_to_install.download()
            argostranslate.package.install_from_path(download_path)
            print("Translation model installed.")
        else:
            print("Translation model already installed.")

        # Get the translation function
        self._translator = argostranslate.translate.get_translation_from_codes(
            self.source_lang, self.target_lang
        )

        if self._translator is None:
            raise RuntimeError(
                f"Failed to load translator for {self.source_lang} -> {self.target_lang}"
            )

        print("Translator ready.")

    def translate(self, text: str) -> str:
        """Translate text from source language to target language.

        Args:
            text: Text to translate.

        Returns:
            Translated text.
        """
        if not text or not text.strip():
            return ""

        self._ensure_model()

        translated = self._translator.translate(text)
        return translated

    def is_loaded(self) -> bool:
        """Check if the translation model is loaded.

        Returns:
            True if model is loaded, False otherwise.
        """
        return self._translator is not None
