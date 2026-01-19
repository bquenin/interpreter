"""Registry for available OCR and translation backends."""

from .base import (
    Language,
    OCRBackend,
    OCRBackendInfo,
    TranslationBackend,
    TranslationBackendInfo,
)


class BackendRegistry:
    """Registry for available OCR and translation backends.

    This class manages the registration and lookup of OCR and translation
    backends. Backends are registered by their class, and the registry
    provides methods to find appropriate backends for a given language
    or language pair.
    """

    def __init__(self):
        self._ocr_backends: list[type[OCRBackend]] = []
        self._translation_backends: list[type[TranslationBackend]] = []

    def register_ocr_backend(self, backend_class: type[OCRBackend]) -> None:
        """Register an OCR backend.

        Args:
            backend_class: The OCR backend class to register.
        """
        if backend_class not in self._ocr_backends:
            self._ocr_backends.append(backend_class)

    def register_translation_backend(self, backend_class: type[TranslationBackend]) -> None:
        """Register a translation backend.

        Args:
            backend_class: The translation backend class to register.
        """
        if backend_class not in self._translation_backends:
            self._translation_backends.append(backend_class)

    def get_ocr_backends(self) -> list[OCRBackendInfo]:
        """Get info for all registered OCR backends.

        Returns:
            List of OCRBackendInfo for all registered backends.
        """
        return [backend.get_info() for backend in self._ocr_backends]

    def get_translation_backends(self) -> list[TranslationBackendInfo]:
        """Get info for all registered translation backends.

        Returns:
            List of TranslationBackendInfo for all registered backends.
        """
        return [backend.get_info() for backend in self._translation_backends]

    def get_ocr_backends_for_language(self, language: Language) -> list[OCRBackendInfo]:
        """Get OCR backends that support a specific source language.

        Args:
            language: The source language to OCR.

        Returns:
            List of OCRBackendInfo for backends supporting this language.
        """
        results = []
        for backend in self._ocr_backends:
            info = backend.get_info()
            if language in info.supported_languages:
                results.append(info)
        return results

    def get_translation_backends_for_pair(
        self, source: Language, target: Language
    ) -> list[TranslationBackendInfo]:
        """Get translation backends that support a specific language pair.

        Args:
            source: The source language.
            target: The target language.

        Returns:
            List of TranslationBackendInfo for backends supporting this pair.
            Sorted with default backend first.
        """
        results = []
        for backend in self._translation_backends:
            info = backend.get_info()
            if info.source_language == source and info.target_language == target:
                results.append(info)
        # Sort so default backends come first
        results.sort(key=lambda x: (not x.is_default, x.name))
        return results

    def get_default_ocr_backend_for_language(self, language: Language) -> type[OCRBackend] | None:
        """Get the default OCR backend for a language.

        Args:
            language: The source language to OCR.

        Returns:
            The default OCR backend class, or None if no backend supports this language.
        """
        for backend in self._ocr_backends:
            info = backend.get_info()
            if language in info.supported_languages:
                return backend
        return None

    def get_default_translation_backend_for_pair(
        self, source: Language, target: Language
    ) -> type[TranslationBackend] | None:
        """Get the default translation backend for a language pair.

        Args:
            source: The source language.
            target: The target language.

        Returns:
            The default translation backend class, or None if no backend supports this pair.
        """
        default_backend = None
        for backend in self._translation_backends:
            info = backend.get_info()
            if info.source_language == source and info.target_language == target:
                if info.is_default:
                    return backend
                if default_backend is None:
                    default_backend = backend
        return default_backend

    def get_ocr_backend_by_id(self, backend_id: str) -> type[OCRBackend] | None:
        """Get an OCR backend by its ID.

        Args:
            backend_id: The backend ID to look up.

        Returns:
            The OCR backend class, or None if not found.
        """
        for backend in self._ocr_backends:
            if backend.get_info().id == backend_id:
                return backend
        return None

    def get_translation_backend_by_id(self, backend_id: str) -> type[TranslationBackend] | None:
        """Get a translation backend by its ID.

        Args:
            backend_id: The backend ID to look up.

        Returns:
            The translation backend class, or None if not found.
        """
        for backend in self._translation_backends:
            if backend.get_info().id == backend_id:
                return backend
        return None

    def get_supported_source_languages(self) -> list[Language]:
        """Get all source languages that have at least one OCR backend.

        Returns:
            List of supported source languages.
        """
        languages = set()
        for backend in self._ocr_backends:
            info = backend.get_info()
            languages.update(info.supported_languages)
        return sorted(languages, key=lambda x: x.display_name)

    def get_supported_target_languages(self, source: Language) -> list[Language]:
        """Get all target languages available for a given source language.

        Args:
            source: The source language.

        Returns:
            List of supported target languages for this source.
        """
        targets = set()
        for backend in self._translation_backends:
            info = backend.get_info()
            if info.source_language == source:
                targets.add(info.target_language)
        return sorted(targets, key=lambda x: x.display_name)


# Global registry instance
_registry = BackendRegistry()


def get_registry() -> BackendRegistry:
    """Get the global backend registry.

    Returns:
        The global BackendRegistry instance.
    """
    return _registry
