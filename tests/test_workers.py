"""Tests for the OCR/translation worker's runtime failure handling (no models, no Qt event loop)."""

from unittest.mock import MagicMock

import pytest

from interpreter.config import Config, OverlayMode
from interpreter.gui.workers import MAX_CONSECUTIVE_TRANSLATION_FAILURES, ProcessWorker
from interpreter.ocr import OCRResult


class _FlakyTranslator:
    """Translator whose translate() raises until told otherwise."""

    name = "flaky"

    def __init__(self):
        self.failing = True
        self.calls = 0

    def load(self):
        pass

    def is_loaded(self):
        return True

    def translate(self, text):
        self.calls += 1
        if self.failing:
            raise RuntimeError("Cannot reach Ollama at http://127.0.0.1:11434")
        return f"<{text}>", False


@pytest.fixture
def worker():
    worker = ProcessWorker(Config())
    worker._ocr = MagicMock()
    worker._ocr.extract_text_regions.return_value = [
        OCRResult("こんにちは", {"x": 0, "y": 0, "width": 10, "height": 10})
    ]
    worker._translator = _FlakyTranslator()
    statuses = []
    failures = []
    texts = []
    worker.translation_status.connect(statuses.append)
    worker.models_failed.connect(failures.append)
    worker.text_ready.connect(texts.append)
    worker.regions_ready.connect(texts.append)
    worker._events = (statuses, failures, texts)
    return worker


def test_repeated_runtime_failures_mark_engine_failed(worker):
    statuses, failures, texts = worker._events

    for _ in range(MAX_CONSECUTIVE_TRANSLATION_FAILURES - 1):
        worker._process_frame("frame")
    assert not worker._translation_failed
    assert statuses == [] and failures == []
    assert texts == ["[こんにちは]"] * (MAX_CONSECUTIVE_TRANSLATION_FAILURES - 1)

    worker._process_frame("frame")
    assert worker._translation_failed
    assert worker.get_failed_models() == ["translation"]
    assert statuses == ["error"]
    assert failures == ["Cannot reach Ollama at http://127.0.0.1:11434"]
    assert "Cannot reach Ollama" in worker.get_failure_message()


def test_success_resets_failure_count(worker):
    statuses, failures, _ = worker._events
    translator = worker._translator

    worker._process_frame("frame")
    worker._process_frame("frame")
    translator.failing = False
    worker._process_frame("frame")
    assert worker._translation_failures == 0
    translator.failing = True
    worker._process_frame("frame")
    worker._process_frame("frame")
    assert not worker._translation_failed
    assert statuses == [] and failures == []


def test_inplace_mode_stops_after_marking_failed(worker):
    statuses, failures, _ = worker._events
    worker.set_mode(OverlayMode.INPLACE)
    worker._ocr.extract_text_regions.return_value = [
        OCRResult("いち", {"x": 0, "y": 0, "width": 1, "height": 1}),
        OCRResult("に", {"x": 0, "y": 0, "width": 1, "height": 1}),
        OCRResult("さん", {"x": 0, "y": 0, "width": 1, "height": 1}),
        OCRResult("よん", {"x": 0, "y": 0, "width": 1, "height": 1}),
    ]

    worker._process_frame("frame")

    assert worker._translation_failed
    assert statuses == ["error"] and len(failures) == 1
    # Stopped at the threshold instead of hammering the dead endpoint for every region
    assert worker._translator.calls == MAX_CONSECUTIVE_TRANSLATION_FAILURES


def test_reload_clears_failure_state(worker, monkeypatch):
    worker._translation_failed = True
    worker._translation_failures = MAX_CONSECUTIVE_TRANSLATION_FAILURES
    worker._translation_error = "old"
    healthy = _FlakyTranslator()
    healthy.failing = False
    monkeypatch.setattr("interpreter.gui.workers.create_translator", lambda config: healthy)

    worker._load_translator()

    assert not worker._translation_failed
    assert worker._translation_failures == 0
    assert worker._translation_error == ""
    assert worker._events[0][-1] == "ready"
