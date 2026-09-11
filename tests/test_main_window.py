"""Tests for the OCR and Translation panel logic of MainWindow, without building the full window."""

import pytest
from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QLineEdit, QPlainTextEdit, QPushButton

from interpreter.config import Config, LLMSettings, OCRBackend, OwocrSettings, TranslationBackend
from interpreter.gui.main_window import MainWindow
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
    return win


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
