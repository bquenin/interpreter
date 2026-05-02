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

    items = {item["text"]: item for item in arranged}
    assert items["Second"]["x"] == 20
    assert items["Second"]["y"] == 15
    assert items["First"]["x"] == 10
    assert items["First"]["y"] >= items["Second"]["y"] + items["Second"]["label_height"] + 4


def test_non_overlapping_regions_keep_original_positions():
    from interpreter.overlay.base import arrange_overlay_regions

    regions = [
        ("Left", {"x": 10, "y": 10, "width": 40, "height": 20}),
        ("Right", {"x": 200, "y": 10, "width": 40, "height": 20}),
    ]
    label_sizes = [(60, 24), (60, 24)]

    arranged = arrange_overlay_regions(regions, label_sizes, scale=1.0, content_offset=(0, 0), padding=4)

    positions = {item["text"]: (item["x"], item["y"]) for item in arranged}
    assert positions == {"Left": (10, 10), "Right": (200, 10)}



def test_vertical_columns_are_ordered_right_to_left_then_top_to_bottom():
    from interpreter.overlay.base import arrange_overlay_regions

    regions = [
        ("left-column", {"x": 100, "y": 10, "width": 20, "height": 60}),
        ("right-column-top", {"x": 180, "y": 10, "width": 20, "height": 60}),
        ("right-column-bottom", {"x": 180, "y": 90, "width": 20, "height": 60}),
    ]
    label_sizes = [(80, 24), (80, 24), (90, 24)]

    arranged = arrange_overlay_regions(regions, label_sizes, scale=1.0, content_offset=(0, 0), padding=4)

    assert [item["text"] for item in arranged] == [
        "right-column-top",
        "right-column-bottom",
        "left-column",
    ]
