"""Tests for the standalone OCR benchmark tooling."""

from __future__ import annotations

import sys
from pathlib import Path

OCR_BENCHMARK_DIR = Path(__file__).resolve().parents[1] / "benchmark" / "ocr"
sys.path.insert(0, str(OCR_BENCHMARK_DIR))

from benchlib import (  # noqa: E402
    bootstrap_cer_delta,
    edit_counts,
    load_json,
    normalize_text,
    percentile,
    select_samples,
    validate_manifest,
)


def test_normalize_text_uses_nfkc_and_ignores_whitespace() -> None:
    assert normalize_text("　ＬＶ １８\n勇者！ ") == "LV18勇者!"


def test_edit_counts_reports_operation_types() -> None:
    assert edit_counts("勇者", "勇士")["substitutions"] == 1
    assert edit_counts("勇者", "勇")["deletions"] == 1
    assert edit_counts("勇", "勇者")["insertions"] == 1


def test_percentile_interpolates() -> None:
    assert percentile([10.0, 20.0, 30.0], 0.95) == 29.0
    assert percentile([], 0.95) is None


def test_corpus_manifest_is_valid_and_readiness_is_explicit() -> None:
    manifest = load_json(OCR_BENCHMARK_DIR / "corpus.json")
    assert validate_manifest(manifest) == []
    assert len(manifest["samples"]) == 44
    assert len(select_samples(manifest)) == 25
    assert len(select_samples(manifest, include_unscored=True)) == 44

    verified_real = [
        sample
        for sample in manifest["samples"]
        if sample["role"] in {"evaluation", "holdout"} and sample["annotation"]["status"] == "verified"
    ]
    assert verified_real == []


def test_bootstrap_detects_a_consistently_better_candidate() -> None:
    def sample(sample_id: str, reference: str, prediction: str) -> dict:
        return {
            "id": sample_id,
            "reference": reference,
            "prediction": prediction,
            "counts": edit_counts(reference, prediction),
            "error": None,
        }

    baseline = [
        sample("one", "あいうえお", "あいう"),
        sample("two", "かきくけこ", "かきく"),
        sample("three", "さしすせそ", "さしす"),
    ]
    candidate = [
        sample("one", "あいうえお", "あいうえお"),
        sample("two", "かきくけこ", "かきくけこ"),
        sample("three", "さしすせそ", "さしすせそ"),
    ]

    result = bootstrap_cer_delta(baseline, candidate, iterations=500, seed=7)
    assert result["delta"] < 0
    assert result["ci95"][1] < 0
