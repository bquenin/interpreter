"""Tests for the OCR and Translation panel logic of MainWindow, without building the full window."""

import pytest
from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QLineEdit, QPlainTextEdit, QPushButton

from interpreter.config import Config, LLMSettings, OCRBackend, OwocrSettings, TranslationBackend
from interpreter.gui.main_window import MainWindow
from interpreter.languages import SOURCE_LANGUAGES
from interpreter.llm_translate import DEFAULT_SYSTEM_PROMPT, PROVIDER_LABELS, PROVIDERS


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _panel(config: Config) -> MainWindow:
    """A MainWindow with only the LLM panel widgets, skipping __init__ (worker, overlays, hotkeys)."""
    win = MainWindow.__new__(MainWindow)
    win._config = config
    llm = config.llm
    win._llm_provider_combo = QComboBox()
    for provider in PROVIDERS:
        win._llm_provider_combo.addItem(PROVIDER_LABELS[provider], provider)
    win._llm_provider_combo.setCurrentIndex(win._llm_provider_combo.findData(llm.provider))
    win._llm_url_edit = QLineEdit(llm.base_url)
    win._llm_model_combo = QComboBox()
    win._llm_model_combo.setEditable(True)
    win._llm_model_combo.setCurrentText(llm.model)
    win._llm_api_key_edit = QLineEdit(llm.api_key)
    win._llm_language_edit = QLineEdit(llm.target_language)
    win._llm_prompt_edit = QPlainTextEdit(llm.system_prompt or DEFAULT_SYSTEM_PROMPT)
    win._llm_refresh_btn = QPushButton()
    win._llm_test_btn = QPushButton()
    win._llm_result_label = QLabel()
    win._llm_refresh_request = None
    win._llm_test_request = None
    win._llm_test_language = config.source_language
    # The Test button reads the pending source language from the OCR group
    win._ocr_engine_combo = QComboBox()
    win._ocr_engine_combo.addItem("MeikiOCR", OCRBackend.MEIKI.value)
    win._ocr_engine_combo.addItem("owocr", OCRBackend.OWOCR.value)
    win._ocr_engine_combo.setCurrentIndex(win._ocr_engine_combo.findData(config.ocr_backend.value))
    win._source_language_combo = QComboBox()
    for language in SOURCE_LANGUAGES:
        win._source_language_combo.addItem(language, language)
    win._source_language_combo.setCurrentIndex(win._source_language_combo.findData(config.source_language))
    return win


def test_llm_test_uses_the_pending_source_language(qapp, monkeypatch):
    """Greptile: Test must validate the language the user selected, not the last applied one."""
    import interpreter.gui.main_window as module

    seen = {}

    def fake_check(settings, source_language):
        seen["language"] = source_language
        return ("Bonjour", 3)

    class _Inline:
        def __init__(self, target, daemon):
            self._target = target

        def start(self):
            self._target()

    monkeypatch.setattr(module, "check_endpoint", fake_check)
    monkeypatch.setattr(module.threading, "Thread", _Inline)
    win = _panel(Config(ocr_backend=OCRBackend.OWOCR, llm=LLMSettings(model="m"), source_language="Japanese"))
    done = []
    win._llm_test_result = type("S", (), {"emit": lambda self, payload: done.append(payload)})()
    win._source_language_combo.setCurrentIndex(win._source_language_combo.findData("Korean"))  # not applied yet

    win._test_llm_endpoint()

    assert seen["language"] == "Korean"
    assert "Korean sample" in win._llm_result_label.toolTip()
    win._on_llm_test_done(done[0])
    assert win._llm_result_label.toolTip() == "OK in 3 ms: Bonjour"

    # Language changed while a test was in flight: the result is discarded
    win._test_llm_endpoint()
    win._source_language_combo.setCurrentIndex(win._source_language_combo.findData("Chinese"))
    win._on_llm_test_done(done[1])
    assert "click Test again" in win._llm_result_label.toolTip()


def _ocr_panel(config: Config) -> MainWindow:
    """A MainWindow with only the OCR panel widgets, skipping __init__."""
    win = MainWindow.__new__(MainWindow)
    win._config = config
    win._ocr_engine_combo = QComboBox()
    win._ocr_engine_combo.addItem("MeikiOCR", OCRBackend.MEIKI.value)
    win._ocr_engine_combo.addItem("owocr", OCRBackend.OWOCR.value)
    win._ocr_engine_combo.setCurrentIndex(win._ocr_engine_combo.findData(config.ocr_backend.value))
    win._owocr_url_edit = QLineEdit(config.owocr.url)
    win._owocr_test_btn = QPushButton()
    win._owocr_result_label = QLabel()
    win._owocr_test_request = None
    return win


def test_owocr_settings_from_ui_normalize_url_and_keep_config_timeout(qapp):
    win = _ocr_panel(Config(ocr_backend=OCRBackend.OWOCR, owocr=OwocrSettings(timeout=4.0)))
    win._owocr_url_edit.setText("http://127.0.0.1:7331/")
    settings = win._owocr_settings_from_ui()
    assert settings == OwocrSettings(url="ws://127.0.0.1:7331", timeout=4.0)
    assert win._selected_ocr_backend() == OCRBackend.OWOCR


def test_stale_owocr_test_results_are_ignored(qapp):
    win = _ocr_panel(Config(ocr_backend=OCRBackend.OWOCR))
    win._owocr_test_btn.setEnabled(False)
    current = win._owocr_settings_from_ui()
    win._owocr_test_request = current

    # A result from an older, superseded request changes nothing
    win._on_owocr_test_done((OwocrSettings(url="ws://old:1"), 5))
    assert win._owocr_result_label.toolTip() == ""
    assert not win._owocr_test_btn.isEnabled()

    # The current request applies
    win._on_owocr_test_done((current, 5))
    assert win._owocr_result_label.toolTip() == "OK in 5 ms"
    assert win._owocr_test_btn.isEnabled()

    # An error string is shown as an error
    pending = win._owocr_settings_from_ui()
    win._owocr_test_request = pending
    win._on_owocr_test_done((pending, "Cannot reach owocr"))
    assert win._owocr_result_label.toolTip() == "Cannot reach owocr"
    assert "d9534f" in win._owocr_result_label.styleSheet()

    # Settings edited while the request was in flight: the result is discarded
    pending = win._owocr_settings_from_ui()
    win._owocr_test_request = pending
    win._owocr_url_edit.setText("ws://changed:1")
    win._on_owocr_test_done((pending, 5))
    assert "click Test again" in win._owocr_result_label.toolTip()


def test_successful_test_against_a_remote_host_warns_about_plaintext(qapp):
    win = _ocr_panel(Config(ocr_backend=OCRBackend.OWOCR, owocr=OwocrSettings(url="ws://192.168.1.20:7331")))
    current = win._owocr_settings_from_ui()
    win._owocr_test_request = current
    win._on_owocr_test_done((current, 7))
    tooltip = win._owocr_result_label.toolTip()
    assert tooltip.startswith("OK in 7 ms")
    assert "unencrypted to 192.168.1.20" in tooltip


def test_ready_status_clears_a_previous_owocr_error(qapp):
    win = _ocr_panel(Config(ocr_backend=OCRBackend.OWOCR))
    win._ocr_status_label = QLabel()
    win._fix_models_btn = QPushButton()
    win._translation_status_label = QLabel("Ready")
    win._fixing_ocr = False
    win._set_owocr_result("Cannot reach owocr", error=True)

    win._on_ocr_status("ready")

    assert win._owocr_result_label.toolTip() == ""
    assert win._ocr_status_label.text() == "Ready"


def test_settings_from_ui_keep_config_only_fields(qapp):
    """Apply must not drop fields that have no widget (context_lines, timeout, request_options)."""
    config = Config(
        translation_backend=TranslationBackend.LLM,
        llm=LLMSettings(model="m", context_lines=5, timeout=12.0, request_options={"reasoning_effort": "none"}),
    )
    win = _panel(config)
    win._llm_model_combo.setCurrentText("other")

    settings = win._llm_settings_from_ui()

    assert settings.model == "other"
    assert settings.context_lines == 5
    assert settings.timeout == 12.0
    assert settings.request_options == {"reasoning_effort": "none"}
    assert settings.request_options is not config.llm.request_options  # a copy, not shared state


def test_settings_from_ui_default_prompt_is_stored_as_none(qapp):
    win = _panel(Config(llm=LLMSettings(model="m")))
    assert win._llm_settings_from_ui().system_prompt is None
    win._llm_prompt_edit.setPlainText("Custom {target_language}")
    assert win._llm_settings_from_ui().system_prompt == "Custom {target_language}"


def test_stale_test_results_are_ignored(qapp):
    win = _panel(Config(llm=LLMSettings(model="m")))
    win._llm_test_btn.setEnabled(False)
    current = win._llm_settings_from_ui()
    win._llm_test_request = current

    # A result from an older, superseded request changes nothing
    win._on_llm_test_done((LLMSettings(model="old"), ("Hello", 5)))
    assert win._llm_result_label.toolTip() == ""
    assert not win._llm_test_btn.isEnabled()

    # The current request applies
    win._on_llm_test_done((current, ("Hello", 5)))
    assert win._llm_result_label.toolTip() == "OK in 5 ms: Hello"
    assert win._llm_test_btn.isEnabled()

    # Settings edited while the request was in flight: the result is discarded
    pending = win._llm_settings_from_ui()
    win._llm_test_request = pending
    win._llm_model_combo.setCurrentText("changed-meanwhile")
    win._on_llm_test_done((pending, ("Hello", 5)))
    assert "click Test again" in win._llm_result_label.toolTip()


def test_stale_model_lists_are_ignored(qapp):
    win = _panel(Config(llm=LLMSettings(model="m")))
    win._llm_refresh_btn.setEnabled(False)
    current = win._llm_settings_from_ui()
    win._llm_refresh_request = current

    win._on_llm_models_listed((LLMSettings(base_url="http://old:1"), ["from-old-server"]))
    assert win._llm_model_combo.count() == 0
    assert not win._llm_refresh_btn.isEnabled()

    # Endpoint changed after the request was sent: list is discarded, model text untouched
    win._llm_url_edit.setText("http://127.0.0.1:9999")
    win._on_llm_models_listed((current, ["a", "b"]))
    assert win._llm_model_combo.count() == 0
    assert win._llm_model_combo.currentText() == "m"
    assert "Endpoint changed" in win._llm_result_label.toolTip()
    assert win._llm_refresh_btn.isEnabled()

    # Matching request and endpoint: list applied, current model kept selected
    win._llm_url_edit.setText(current.base_url)
    current = win._llm_settings_from_ui()
    win._llm_refresh_request = current
    win._on_llm_models_listed((current, ["a", "m"]))
    assert [win._llm_model_combo.itemText(i) for i in range(win._llm_model_combo.count())] == ["a", "m"]
    assert win._llm_model_combo.currentText() == "m"
    assert win._llm_result_label.toolTip() == "2 model(s) found"
