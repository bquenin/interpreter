"""Tests for inplace overlay layout helpers."""

import importlib.metadata
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

_real_version = importlib.metadata.version


def _version_with_fallback(name: str) -> str:
    if name == "interpreter-v2":
        return "0.0"
    return _real_version(name)


importlib.metadata.version = _version_with_fallback


def test_stack_overlapping_regions_moves_second_label_down():
    from interpreter.overlay.base import arrange_overlay_regions

    regions = [
        ("First", {"x": 10, "y": 10, "width": 40, "height": 20}),
        ("Second", {"x": 20, "y": 15, "width": 40, "height": 20}),
    ]
    label_sizes = [(80, 24), (90, 24)]

    arranged = arrange_overlay_regions(regions, label_sizes, scale=1.0, content_offset=(0, 0), padding=4)

    assert arranged[0]["x"] == 10
    assert arranged[0]["y"] == 10
    assert arranged[1]["x"] == 20
    assert arranged[1]["y"] >= arranged[0]["y"] + arranged[0]["label_height"] + 4


def test_non_overlapping_regions_keep_original_positions():
    from interpreter.overlay.base import arrange_overlay_regions

    regions = [
        ("Left", {"x": 10, "y": 10, "width": 40, "height": 20}),
        ("Right", {"x": 200, "y": 10, "width": 40, "height": 20}),
    ]
    label_sizes = [(60, 24), (60, 24)]

    arranged = arrange_overlay_regions(regions, label_sizes, scale=1.0, content_offset=(0, 0), padding=4)

    assert [(item["x"], item["y"]) for item in arranged] == [(10, 10), (200, 10)]
