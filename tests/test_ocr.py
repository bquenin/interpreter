"""Tests for the built-in MeikiOCR pipeline's post-processing (no model: run_ocr is faked)."""

from unittest.mock import MagicMock

import numpy as np
import pytest

from interpreter.ocr import OCR, OCRResult


def _chars(text: str, x: int, y: int, conf: float = 0.9, size: int = 10) -> list[dict]:
    """One character box per glyph, laid out left to right."""
    return [
        {"char": c, "conf": conf, "bbox": [x + i * size, y, x + (i + 1) * size, y + size]} for i, c in enumerate(text)
    ]


def _ocr(results: list[dict], threshold: float = 0.6) -> OCR:
    ocr = OCR(confidence_threshold=threshold)
    ocr._model = MagicMock()
    ocr._model.run_ocr.return_value = results
    return ocr


FRAME = np.zeros((100, 200, 4), dtype=np.uint8)


def test_name():
    assert OCR().name == "MeikiOCR"
    assert not OCR().is_loaded()


def test_low_confidence_lines_are_filtered():
    ocr = _ocr(
        [
            {"text": "よい", "chars": _chars("よい", 0, 0, conf=0.9)},
            {"text": "わるい", "chars": _chars("わるい", 0, 50, conf=0.3)},
        ]
    )
    assert [r.text for r in ocr.extract_text_regions(FRAME)] == ["よい"]


def test_punctuation_does_not_drag_the_average_down():
    chars = [*_chars("やあ", 0, 0, conf=0.9), {"char": "。", "conf": 0.1, "bbox": [20, 0, 30, 10]}]
    ocr = _ocr([{"text": "やあ。", "chars": chars}])
    assert [r.text for r in ocr.extract_text_regions(FRAME)] == ["やあ。"]


def test_threshold_can_change_between_frames():
    ocr = _ocr([{"text": "あ", "chars": _chars("あ", 0, 0, conf=0.5)}])
    assert ocr.extract_text_regions(FRAME) == []
    ocr.confidence_threshold = 0.4
    assert [r.text for r in ocr.extract_text_regions(FRAME)] == ["あ"]


def test_invalid_or_missing_boxes_are_skipped():
    ocr = _ocr(
        [
            {"text": "負", "chars": [{"char": "負", "conf": 0.9, "bbox": [-5, 0, 10, 10]}]},
            {"text": "空", "chars": [{"char": "空", "conf": 0.9, "bbox": [10, 10, 10, 20]}]},
            {"text": "無", "chars": [{"char": "無", "conf": 0.9}]},
            {"text": "", "chars": _chars("x", 0, 0)},
        ]
    )
    assert ocr.extract_text_regions(FRAME) == []


def test_overlapping_detections_keep_the_longer_text():
    ocr = _ocr(
        [
            {"text": "こんに", "chars": _chars("こんに", 0, 0)},
            {"text": "こんにちは", "chars": _chars("こんにちは", 0, 0)},
        ]
    )
    assert [r.text for r in ocr.extract_text_regions(FRAME)] == ["こんにちは"]


def test_horizontal_neighbours_merge_and_stacked_lines_stay_apart():
    ocr = _ocr(
        [
            {"text": "上", "chars": _chars("上", 0, 0)},
            {"text": "の", "chars": _chars("の", 12, 0)},  # 2 px gap, same row
            {"text": "下", "chars": _chars("下", 0, 40)},  # separate row
        ]
    )
    regions = ocr.extract_text_regions(FRAME)
    assert regions == [
        OCRResult("上の", {"x": 0, "y": 0, "width": 22, "height": 10}),
        OCRResult("下", {"x": 0, "y": 40, "width": 10, "height": 10}),
    ]


def test_far_apart_lines_on_one_row_are_separate_regions():
    ocr = _ocr(
        [
            {"text": "左", "chars": _chars("左", 0, 0)},
            {"text": "右", "chars": _chars("右", 100, 0)},
        ]
    )
    assert [r.text for r in ocr.extract_text_regions(FRAME)] == ["左", "右"]


def test_clean_text_collapses_whitespace():
    assert OCR()._clean_text("  a \n\t b  ") == "a b"
    assert OCR()._clean_text("") == ""


def test_model_receives_rgb():
    ocr = _ocr([])
    frame = np.zeros((2, 2, 4), dtype=np.uint8)
    frame[:, :, 0] = 255  # blue in BGRA
    ocr.extract_text_regions(frame)
    sent = ocr._model.run_ocr.call_args.args[0]
    assert sent.shape == (2, 2, 3)
    assert tuple(sent[0, 0]) == (0, 0, 255)


@pytest.mark.parametrize("empty", [[], [{"text": "x", "chars": []}]])
def test_no_results_give_no_regions(empty):
    assert _ocr(empty).extract_text_regions(FRAME) == []
