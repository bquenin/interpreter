"""Tests for language-aware OCR and translation wrappers."""

import importlib.metadata
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import importlib.metadata

_real_version = importlib.metadata.version


def _version_with_fallback(name: str) -> str:
    if name == "interpreter-v2":
        return "0.0"
    return _real_version(name)


importlib.metadata.version = _version_with_fallback

import types


def test_translator_uses_japanese_backend(monkeypatch):
    from interpreter import translate as translate_module
    from interpreter.config import SourceLanguage

    class FakeJapaneseTranslator:
        def __init__(self, *args, **kwargs):
            self.label = "ja"

    class FakeChineseTranslator:
        def __init__(self, *args, **kwargs):
            self.label = "zh"

    monkeypatch.setattr(translate_module, "JapaneseTranslator", FakeJapaneseTranslator)
    monkeypatch.setattr(translate_module, "ChineseTranslator", FakeChineseTranslator)

    translator = translate_module.Translator(source_language=SourceLanguage.JAPANESE)

    assert translator._backend.label == "ja"


def test_translator_uses_chinese_backend(monkeypatch):
    from interpreter import translate as translate_module
    from interpreter.config import SourceLanguage

    class FakeJapaneseTranslator:
        def __init__(self, *args, **kwargs):
            self.label = "ja"

    class FakeChineseTranslator:
        def __init__(self, *args, **kwargs):
            self.label = "zh"

    monkeypatch.setattr(translate_module, "JapaneseTranslator", FakeJapaneseTranslator)
    monkeypatch.setattr(translate_module, "ChineseTranslator", FakeChineseTranslator)

    translator = translate_module.Translator(source_language=SourceLanguage.CHINESE)

    assert translator._backend.label == "zh"


def test_ocr_uses_japanese_backend(monkeypatch):
    from interpreter import ocr as ocr_module
    from interpreter.config import SourceLanguage

    class FakeJapaneseOCR:
        def __init__(self, *args, **kwargs):
            self.label = "ja"

    monkeypatch.setattr(ocr_module, "JapaneseOCR", FakeJapaneseOCR)

    ocr = ocr_module.OCR(source_language=SourceLanguage.JAPANESE)

    assert ocr._backend.label == "ja"


def test_ocr_uses_chinese_backend(monkeypatch):
    from interpreter import ocr as ocr_module
    from interpreter.config import SourceLanguage

    class FakeChineseOCR:
        def __init__(self, *args, **kwargs):
            self.label = "zh"

    fake_module = types.ModuleType("interpreter.ocr_rapid")
    fake_module.ChineseOCR = FakeChineseOCR
    monkeypatch.setitem(sys.modules, "interpreter.ocr_rapid", fake_module)

    ocr = ocr_module.OCR(source_language=SourceLanguage.CHINESE)

    assert ocr._backend.label == "zh"
