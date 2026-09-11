"""Tests for the OCR/translation worker's runtime failure handling (no models, no Qt event loop)."""

from unittest.mock import MagicMock

import pytest

from interpreter.config import Config, OverlayMode
from interpreter.gui.workers import MAX_CONSECUTIVE_OCR_FAILURES, MAX_CONSECUTIVE_TRANSLATION_FAILURES, ProcessWorker
from interpreter.ocr import OCRResult
from interpreter.owocr_ocr import OwocrOCRError


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


class _FakeOCR:
    """OCR engine whose extract_text_regions() raises until told otherwise."""

    name = "fake-ocr"

    def __init__(self):
        self.failing = False
        self.confidence_threshold = 0.0
        self.closed = False

    def load(self):
        pass

    def is_loaded(self):
        return True

    def close(self):
        self.closed = True

    def extract_text_regions(self, frame):
        if self.failing:
            raise OwocrOCRError("Cannot reach owocr at ws://127.0.0.1:7331")
        return [OCRResult("こんにちは", {"x": 0, "y": 0, "width": 10, "height": 10})]


@pytest.fixture
def ocr_worker():
    worker = ProcessWorker(Config())
    worker._ocr = _FakeOCR()
    worker._ocr.failing = True
    worker._translator = _FlakyTranslator()
    worker._translator.failing = False
    statuses = []
    failures = []
    outputs = []
    worker.ocr_status.connect(statuses.append)
    worker.models_failed.connect(failures.append)
    worker.text_ready.connect(outputs.append)
    worker.regions_ready.connect(outputs.append)
    worker.ocr_results_ready.connect(outputs.append)
    worker._events = (statuses, failures, outputs)
    return worker


def test_repeated_ocr_failures_mark_engine_failed(ocr_worker):
    statuses, failures, outputs = ocr_worker._events

    for _ in range(MAX_CONSECUTIVE_OCR_FAILURES - 1):
        ocr_worker._process_frame("frame")
    assert not ocr_worker._ocr_failed
    assert statuses == [] and failures == [] and outputs == []

    ocr_worker._process_frame("frame")
    assert ocr_worker._ocr_failed
    assert ocr_worker.get_failed_models() == ["ocr"]
    assert statuses == ["error"]
    assert failures == ["Cannot reach owocr at ws://127.0.0.1:7331"]
    assert outputs == []  # a failed frame emits nothing, and the loop survives


def test_ocr_success_resets_failure_count(ocr_worker):
    statuses, failures, _ = ocr_worker._events
    ocr_worker._process_frame("frame")
    ocr_worker._process_frame("frame")
    ocr_worker._ocr.failing = False
    ocr_worker._process_frame("frame")
    assert ocr_worker._ocr_failures == 0
    ocr_worker._ocr.failing = True
    ocr_worker._process_frame("frame")
    ocr_worker._process_frame("frame")
    assert not ocr_worker._ocr_failed
    assert statuses == [] and failures == []


def test_reload_ocr_builds_a_fresh_engine_and_closes_the_old_one(ocr_worker, monkeypatch):
    old = ocr_worker._ocr
    ocr_worker._ocr_failed = True
    ocr_worker._ocr_failures = MAX_CONSECUTIVE_OCR_FAILURES
    ocr_worker._ocr_error = "old"
    ocr_worker._confidence_threshold = 0.42
    fresh = _FakeOCR()
    monkeypatch.setattr("interpreter.gui.workers.create_ocr", lambda config: fresh)

    ocr_worker._load_ocr()

    assert ocr_worker._ocr is fresh
    assert old.closed
    assert fresh.confidence_threshold == 0.42
    assert not ocr_worker._ocr_failed
    assert ocr_worker._ocr_failures == 0
    assert ocr_worker._ocr_error == ""
    assert ocr_worker._events[0] == ["loading", "ready"]


def test_reload_ocr_failure_is_recorded(ocr_worker, monkeypatch):
    def broken(config):
        raise RuntimeError("Cannot reach owocr")

    monkeypatch.setattr("interpreter.gui.workers.create_ocr", broken)
    ocr_worker._load_ocr()
    assert ocr_worker._ocr is None
    assert ocr_worker._ocr_failed
    assert ocr_worker._ocr_error == "Cannot reach owocr"
    assert ocr_worker._events[0] == ["loading", "error"]


def test_stop_during_a_frame_suppresses_emits(ocr_worker):
    """A frame that finishes after stop() must not emit on receivers being torn down."""
    _, _, outputs = ocr_worker._events
    ocr = ocr_worker._ocr
    ocr.failing = False
    original = ocr.extract_text_regions

    def extract_then_stop(frame):
        ocr_worker.stop()  # e.g. the window quit while the engine was busy
        return original(frame)

    ocr.extract_text_regions = extract_then_stop
    ocr_worker._process_frame("frame")
    assert outputs == []
    assert ocr_worker._stopped


def test_stop_waits_for_the_worker_thread(monkeypatch):
    """stop() returns only once the thread is done, so the caller can safely drop the worker."""
    import threading

    started = threading.Event()
    release = threading.Event()

    class _SlowOCR(_FakeOCR):
        def extract_text_regions(self, frame):
            started.set()
            release.wait(5)
            return []

    healthy = _FlakyTranslator()
    healthy.failing = False
    monkeypatch.setattr("interpreter.gui.workers.create_ocr", lambda config: _SlowOCR())
    monkeypatch.setattr("interpreter.gui.workers.create_translator", lambda config: healthy)
    worker = ProcessWorker(Config())
    worker.start(0.6)
    worker.submit_frame("frame")
    assert started.wait(5)

    thread = worker._thread
    release.set()
    worker.stop()
    assert not thread.is_alive()


def test_reload_ocr_sets_the_flag_for_the_worker_loop(ocr_worker):
    assert not ocr_worker._reload_ocr
    ocr_worker.reload_ocr()
    assert ocr_worker._reload_ocr


def test_reload_builds_a_fresh_engine_so_caches_do_not_leak_across_settings(monkeypatch):
    """Changing model, target language or prompt must not reuse the old engine's cache."""
    from interpreter.config import LLMSettings, TranslationBackend
    from interpreter.llm_translate import LLMTranslator

    config = Config(translation_backend=TranslationBackend.LLM, llm=LLMSettings(model="m", target_language="English"))
    worker = ProcessWorker(config)
    monkeypatch.setattr(LLMTranslator, "load", lambda self: None)

    worker._load_translator()
    first = worker._translator
    first._cache.put("こんにちは", "Hello")
    assert first.translate("こんにちは") == ("Hello", True)

    config.llm = LLMSettings(model="m", target_language="French")
    worker._load_translator()
    second = worker._translator

    assert second is not first
    assert second._cache.get("こんにちは") is None
    assert second.system_prompt != first.system_prompt
