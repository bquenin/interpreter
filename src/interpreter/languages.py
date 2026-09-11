"""Source languages the app can read, and cheap script checks for their text.

The OCR output is gated on "does this look like text in the source language?"
before translation, so that OCR garbage from decorations or UI chrome is not
translated. The check is deliberately loose: it only asks whether at least one
character belongs to the language's script.
"""

DEFAULT_SOURCE_LANGUAGE = "Japanese"

# Display names double as config values and as the words used in the LLM prompt.
SOURCE_LANGUAGES = (
    "Japanese",
    "Chinese",
    "Korean",
    "English",
    "French",
    "German",
    "Spanish",
    "Italian",
    "Portuguese",
    "Russian",
)

# Inclusive code point ranges per script
_KANA = ((0x3040, 0x309F), (0x30A0, 0x30FF), (0xFF65, 0xFF9F))  # hiragana, katakana, half-width katakana
_HAN = ((0x4E00, 0x9FFF), (0x3400, 0x4DBF), (0xF900, 0xFAFF))  # CJK unified, extension A, compatibility
_HANGUL = ((0xAC00, 0xD7AF), (0x1100, 0x11FF), (0x3130, 0x318F))  # syllables, jamo, compatibility jamo
_LATIN = ((0x41, 0x5A), (0x61, 0x7A), (0xC0, 0x24F), (0xFF21, 0xFF3A), (0xFF41, 0xFF5A))  # incl. accents, full-width
_CYRILLIC = ((0x0400, 0x04FF),)

_SCRIPTS = {
    "Japanese": _KANA + _HAN,
    "Chinese": _HAN,
    "Korean": _HANGUL + _HAN,  # hanja still appear in some games
    "English": _LATIN,
    "French": _LATIN,
    "German": _LATIN,
    "Spanish": _LATIN,
    "Italian": _LATIN,
    "Portuguese": _LATIN,
    "Russian": _CYRILLIC,
}
assert set(_SCRIPTS) == set(SOURCE_LANGUAGES)

# Samples used to warm up and test a translation endpoint.
SAMPLE_TEXT = {
    "Japanese": "はじめまして。わたしはユウキです。",
    "Chinese": "你好，勇者。欢迎来到我们的村庄。",
    "Korean": "안녕하세요, 용사님. 우리 마을에 오신 것을 환영합니다.",
    "English": "Welcome, brave hero. The village needs your help.",
    "French": "Bienvenue, brave héros. Le village a besoin de ton aide.",
    "German": "Willkommen, tapferer Held. Das Dorf braucht deine Hilfe.",
    "Spanish": "Bienvenido, valiente héroe. El pueblo necesita tu ayuda.",
    "Italian": "Benvenuto, coraggioso eroe. Il villaggio ha bisogno del tuo aiuto.",
    "Portuguese": "Bem-vindo, bravo herói. A vila precisa da sua ajuda.",
    "Russian": "Добро пожаловать, храбрый герой. Деревне нужна твоя помощь.",
}
assert set(SAMPLE_TEXT) == set(SOURCE_LANGUAGES)


def normalize_source_language(value: object) -> str:
    """Map a config value to a supported language name (case-insensitive), or the default."""
    text = str(value or "").strip().lower()
    for language in SOURCE_LANGUAGES:
        if language.lower() == text:
            return language
    return DEFAULT_SOURCE_LANGUAGE


def contains_script(text: str, language: str) -> bool:
    """True if ``text`` has at least one character from ``language``'s script."""
    ranges = _SCRIPTS.get(language, _SCRIPTS[DEFAULT_SOURCE_LANGUAGE])
    for char in text:
        code = ord(char)
        for low, high in ranges:
            if low <= code <= high:
                return True
    return False


def contains_japanese(text: str) -> bool:
    """Check if text contains Japanese characters (kana or kanji)."""
    return contains_script(text, "Japanese")
