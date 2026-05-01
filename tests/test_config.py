"""Tests for config source language support."""

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


def test_config_loads_source_language_from_yaml(tmp_path):
    from interpreter.config import Config, SourceLanguage

    config_path = tmp_path / "config.yml"
    config_path.write_text('source_language: chinese\n', encoding="utf-8")

    config = Config.load(str(config_path))

    assert config.source_language == SourceLanguage.CHINESE


def test_config_invalid_source_language_falls_back_to_japanese(tmp_path):
    from interpreter.config import Config, SourceLanguage

    config_path = tmp_path / "config.yml"
    config_path.write_text('source_language: klingon\n', encoding="utf-8")

    config = Config.load(str(config_path))

    assert config.source_language == SourceLanguage.JAPANESE


def test_config_save_round_trips_source_language(tmp_path):
    from interpreter.config import Config, SourceLanguage

    config_path = tmp_path / "config.yml"
    config = Config(source_language=SourceLanguage.CHINESE)

    config.save(str(config_path))
    loaded = Config.load(str(config_path))

    assert loaded.source_language == SourceLanguage.CHINESE
    assert "source_language: chinese" in Path(config_path).read_text(encoding="utf-8")


def test_active_model_names_match_source_language():
    from interpreter.config import (
        SourceLanguage,
        get_active_ocr_model_name,
        get_active_translation_model_name,
    )

    assert get_active_ocr_model_name(SourceLanguage.JAPANESE) == "MeikiOCR"
    assert get_active_ocr_model_name(SourceLanguage.CHINESE) == "RapidOCR"
    assert get_active_translation_model_name(SourceLanguage.JAPANESE) == "Sugoi V4"
    assert get_active_translation_model_name(SourceLanguage.CHINESE) == "OPUS-MT zh-en"
