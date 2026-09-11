"""Tests for source languages other than Japanese: script checks, config, engines, worker gate, GUI."""

from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QLineEdit, QPushButton

from interpreter.config import Config, LLMSettings, OCRBackend, OverlayMode, OwocrSettings, TranslationBackend
from interpreter.gui.main_window import MainWindow
from interpreter.gui.workers import ProcessWorker
from interpreter.languages import (
    DEFAULT_SOURCE_LANGUAGE,
    SAMPLE_TEXT,
    SOURCE_LANGUAGES,
    contains_japanese,
    contains_script,
    normalize_source_language,
)
from interpreter.llm_translate import DEFAULT_SYSTEM_PROMPT, LLMTranslator, check_endpoint
from interpreter.models import ModelLoadError
from interpreter.ocr import OCRResult
from interpreter.translate import SUGOI_ONLY_JAPANESE, Translator, create_translator


class TestScriptChecks:
    @pytest.mark.parametrize("language", SOURCE_LANGUAGES)
    def test_each_language_accepts_its_own_sample(self, language):
        assert contains_script(SAMPLE_TEXT[language], language)

    @pytest.mark.parametrize(
        ("text", "language", "expected"),
        [
            ("こんにちは", "Japanese", True),
            ("勇者", "Japanese", True),
            ("ｶﾀｶﾅ", "Japanese", True),
            ("Hello", "Japanese", False),
            ("你好", "Chinese", True),
            ("こんにちは", "Chinese", False),  # kana only, no Han
            ("안녕", "Korean", True),
            ("漢字", "Korean", True),  # hanja
            ("Hello", "Korean", False),
            ("Hello", "English", True),
            ("héros", "French", True),
            ("Ｈｅｌｌｏ", "English", True),  # full-width Latin from some OCR engines
            ("こんにちは", "English", False),
            ("12345 !?", "English", False),
            ("Привет", "Russian", True),
            ("Hello", "Russian", False),
            ("", "Japanese", False),
        ],
    )
    def test_script_membership(self, text, language, expected):
        assert contains_script(text, language) is expected

    def test_unknown_language_falls_back_to_japanese_rules(self):
        assert contains_script("こんにちは", "Klingon")
        assert not contains_script("Hello", "Klingon")

    def test_contains_japanese_is_kept_for_callers(self):
        assert contains_japanese("やあ")
        assert not contains_japanese("hi")

    def test_normalize_source_language(self):
        assert normalize_source_language("french") == "French"
        assert normalize_source_language(" KOREAN ") == "Korean"
        assert normalize_source_language("Klingon") == DEFAULT_SOURCE_LANGUAGE
        assert normalize_source_language(None) == DEFAULT_SOURCE_LANGUAGE


class TestConfig:
    def test_default_is_japanese_and_is_written(self, tmp_path):
        path = tmp_path / "config.yml"
        Config().save(str(path))
        assert "source_language: Japanese" in path.read_text(encoding="utf-8")
        assert Config.load(str(path)).source_language == "Japanese"

    def test_round_trip(self, tmp_path):
        path = tmp_path / "config.yml"
        Config(source_language="Korean").save(str(path))
        assert Config.load(str(path)).source_language == "Korean"

    def test_case_insensitive_and_invalid_values(self, tmp_path):
        path = tmp_path / "config.yml"
        path.write_text("source_language: german\n", encoding="utf-8")
        assert Config.load(str(path)).source_language == "German"
        path.write_text("source_language: klingon\n", encoding="utf-8")
        assert Config.load(str(path)).source_language == "Japanese"
        path.write_text("window_title: x\n", encoding="utf-8")
        assert Config.load(str(path)).source_language == "Japanese"


class TestTranslationEngines:
    def test_sugoi_refuses_non_japanese_sources(self):
        with pytest.raises(ModelLoadError, match="only translates Japanese"):
            create_translator(Config(source_language="Chinese"))
        assert isinstance(create_translator(Config(source_language="Japanese")), Translator)

    def test_llm_engine_receives_the_source_language(self):
        config = Config(
            translation_backend=TranslationBackend.LLM, llm=LLMSettings(model="m"), source_language="Korean"
        )
        translator = create_translator(config)
        assert isinstance(translator, LLMTranslator)
        assert translator.source_language == "Korean"
        assert translator.sample_text == SAMPLE_TEXT["Korean"]

    def test_default_prompt_names_both_languages(self):
        translator = LLMTranslator(LLMSettings(model="m", target_language="English"), source_language="Chinese")
        prompt = translator.system_prompt
        assert "from Chinese into English" in prompt
        assert "{source_language}" not in prompt and "{target_language}" not in prompt
        assert "{source_language}" in DEFAULT_SYSTEM_PROMPT

    def test_old_custom_prompts_without_the_placeholder_still_work(self):
        settings = LLMSettings(model="m", target_language="French", system_prompt="Translate to {target_language}.")
        translator = LLMTranslator(settings, source_language="English")
        assert translator.system_prompt == "Translate to French."

    def test_warmup_and_test_use_a_sample_in_the_source_language(self):
        translator = LLMTranslator(LLMSettings(model="m"), source_language="Russian")
        translator._session.post = MagicMock(
            return_value=MagicMock(
                status_code=200,
                json=MagicMock(return_value={"message": {"content": "ok"}}),
                raise_for_status=MagicMock(),
            )
        )
        translator.load()
        sent = translator._session.post.call_args.kwargs["json"]["messages"]
        assert sent[-1]["content"] == SAMPLE_TEXT["Russian"]
        assert "from Russian" in sent[0]["content"]

    def test_check_endpoint_translates_the_source_sample(self, monkeypatch):
        seen = {}

        def fake_load(self):
            self._loaded = True

        def fake_translate(self, text):
            seen["text"] = text
            return "Bonjour", False

        monkeypatch.setattr(LLMTranslator, "load", fake_load)
        monkeypatch.setattr(LLMTranslator, "translate", fake_translate)
        translation, ms = check_endpoint(LLMSettings(model="m"), "German")
        assert translation == "Bonjour" and ms >= 0
        assert seen["text"] == SAMPLE_TEXT["German"]


class _EchoTranslator:
    name = "echo"

    def __init__(self):
        self.calls = []

    def load(self):
        pass

    def is_loaded(self):
        return True

    def translate(self, text):
        self.calls.append(text)
        return f"<{text}>", False


def _worker(source_language: str, regions: list[OCRResult], mode=OverlayMode.INPLACE):
    worker = ProcessWorker(Config(source_language=source_language))
    worker.set_mode(mode)
    worker._ocr = MagicMock()
    worker._ocr.extract_text_regions.return_value = regions
    worker._translator = _EchoTranslator()
    outputs = []
    worker.regions_ready.connect(outputs.append)
    worker.text_ready.connect(outputs.append)
    return worker, outputs


class TestWorkerGate:
    REGIONS = [
        OCRResult("Hello", {"x": 0, "y": 0, "width": 1, "height": 1}),
        OCRResult("こんにちは", {"x": 0, "y": 10, "width": 1, "height": 1}),
        OCRResult("###", {"x": 0, "y": 20, "width": 1, "height": 1}),
    ]

    def test_japanese_source_keeps_only_japanese_regions(self):
        worker, outputs = _worker("Japanese", self.REGIONS)
        worker._process_frame("frame")
        assert worker._translator.calls == ["こんにちは"]
        assert outputs == [[["<こんにちは>", {"x": 0, "y": 10, "width": 1, "height": 1}]]]  # Qt turns tuples into lists

    def test_english_source_keeps_only_latin_regions(self):
        worker, outputs = _worker("English", self.REGIONS)
        worker._process_frame("frame")
        assert worker._translator.calls == ["Hello"]
        assert outputs == [[["<Hello>", {"x": 0, "y": 0, "width": 1, "height": 1}]]]

    def test_frame_without_source_text_is_not_translated(self):
        worker, outputs = _worker("Russian", self.REGIONS)
        worker._process_frame("frame")
        assert worker._translator.calls == []
        assert outputs == [[]]

    def test_banner_mode_uses_the_same_gate(self):
        worker, outputs = _worker("English", self.REGIONS[:1], mode=OverlayMode.BANNER)
        worker._process_frame("frame")
        assert outputs == ["<Hello>"]

    def test_language_change_in_config_applies_on_the_next_frame(self):
        worker, _ = _worker("Japanese", self.REGIONS)
        worker._process_frame("frame")
        worker._config.source_language = "English"
        worker._process_frame("frame")
        assert worker._translator.calls == ["こんにちは", "Hello"]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _panel(config: Config) -> MainWindow:
    """A MainWindow with the OCR group's widgets plus what the Apply guards touch, skipping __init__."""
    win = MainWindow.__new__(MainWindow)
    win._config = config
    win._ocr_engine_combo = QComboBox()
    win._ocr_engine_combo.addItem("MeikiOCR", OCRBackend.MEIKI.value)
    win._ocr_engine_combo.addItem("owocr", OCRBackend.OWOCR.value)
    win._ocr_engine_combo.setCurrentIndex(win._ocr_engine_combo.findData(config.ocr_backend.value))
    win._source_language_combo = QComboBox()
    for language in SOURCE_LANGUAGES:
        win._source_language_combo.addItem(language, language)
    win._source_language_combo.setCurrentIndex(win._source_language_combo.findData(config.source_language))
    win._owocr_panel = MagicMock()
    win._owocr_url_edit = QLineEdit(config.owocr.url)
    win._owocr_result_label = QLabel()
    win._ocr_engine_label = QLabel()
    win._ocr_status_label = QLabel()
    win._translation_status_label = QLabel()
    win._fix_models_btn = QPushButton()
    win._engine_combo = QComboBox()
    win._engine_combo.addItem("Sugoi", TranslationBackend.SUGOI.value)
    win._engine_combo.addItem("LLM", TranslationBackend.LLM.value)
    win._engine_combo.setCurrentIndex(win._engine_combo.findData(config.translation_backend.value))
    win._process_worker = MagicMock()
    win._grow_to_fit = MagicMock()
    win.statusBar = MagicMock()
    config.save = MagicMock()
    return win


class TestMainWindow:
    def test_meiki_pins_the_language_to_japanese(self, qapp):
        win = _panel(Config(source_language="Korean"))  # e.g. hand-edited config with MeikiOCR
        win._sync_source_language_combo()
        assert not win._source_language_combo.isEnabled()
        assert win._source_language_combo.currentData() == "Japanese"
        assert win._selected_source_language() == "Japanese"

    def test_owocr_unlocks_the_language(self, qapp):
        win = _panel(Config(ocr_backend=OCRBackend.OWOCR, source_language="Korean"))
        win._sync_source_language_combo()
        assert win._source_language_combo.isEnabled()
        assert win._selected_source_language() == "Korean"

    def test_switching_engine_back_to_meiki_resets_the_language(self, qapp):
        win = _panel(Config(ocr_backend=OCRBackend.OWOCR, source_language="Korean"))
        win._ocr_engine_combo.setCurrentIndex(win._ocr_engine_combo.findData(OCRBackend.MEIKI.value))
        win._on_ocr_engine_changed(0)
        assert win._selected_source_language() == "Japanese"
        assert not win._source_language_combo.isEnabled()

    def test_apply_ocr_refuses_non_japanese_with_sugoi(self, qapp):
        config = Config(ocr_backend=OCRBackend.OWOCR, owocr=OwocrSettings())
        win = _panel(config)
        win._source_language_combo.setCurrentIndex(win._source_language_combo.findData("English"))

        win._apply_ocr_settings()

        assert win._owocr_result_label.toolTip() == SUGOI_ONLY_JAPANESE
        assert config.source_language == "Japanese"
        config.save.assert_not_called()
        win._process_worker.reload_ocr.assert_not_called()

    def test_apply_ocr_saves_the_language_and_reloads_both_engines(self, qapp):
        config = Config(ocr_backend=OCRBackend.OWOCR, translation_backend=TranslationBackend.LLM)
        win = _panel(config)
        win._source_language_combo.setCurrentIndex(win._source_language_combo.findData("Chinese"))

        win._apply_ocr_settings()

        assert config.source_language == "Chinese"
        config.save.assert_called_once()
        win._process_worker.reload_ocr.assert_called_once()
        win._process_worker.reload_translation.assert_called_once()

    def test_apply_ocr_with_meiki_forces_japanese(self, qapp):
        config = Config(
            ocr_backend=OCRBackend.OWOCR, translation_backend=TranslationBackend.LLM, source_language="Chinese"
        )
        win = _panel(config)
        win._ocr_engine_combo.setCurrentIndex(win._ocr_engine_combo.findData(OCRBackend.MEIKI.value))

        win._apply_ocr_settings()

        assert config.ocr_backend == OCRBackend.MEIKI
        assert config.source_language == "Japanese"
        win._process_worker.reload_translation.assert_called_once()  # prompt no longer says Chinese

    def test_fix_models_does_not_delete_sugoi_for_a_language_conflict(self, qapp, monkeypatch):
        """A hand-edited config pairing Sugoi with a non-Japanese source must not wipe the model cache."""
        config = Config(
            ocr_backend=OCRBackend.OWOCR, translation_backend=TranslationBackend.SUGOI, source_language="Korean"
        )
        win = _panel(config)
        win._fixing_ocr = win._fixing_translation = False
        win._process_worker.get_failed_models.return_value = ["translation"]
        deleted = []
        monkeypatch.setattr("interpreter.models.delete_model_cache", deleted.append)

        win._on_fix_models()

        assert deleted == []
        win._process_worker.reload_translation.assert_called_once()
        win._process_worker.stop.assert_not_called()  # no worker restart, nothing to download

    def test_apply_translation_refuses_sugoi_with_non_japanese_source(self, qapp):
        config = Config(
            ocr_backend=OCRBackend.OWOCR, translation_backend=TranslationBackend.LLM, source_language="English"
        )
        win = _panel(config)
        win._engine_combo.setCurrentIndex(win._engine_combo.findData(TranslationBackend.SUGOI.value))

        win._apply_translation_settings()

        assert config.translation_backend == TranslationBackend.LLM
        assert win._translation_status_label.toolTip() == SUGOI_ONLY_JAPANESE
        win.statusBar().showMessage.assert_called_with(SUGOI_ONLY_JAPANESE)
        config.save.assert_not_called()
