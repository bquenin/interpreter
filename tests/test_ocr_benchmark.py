"""Tests for the standalone OCR benchmark tooling."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

OCR_BENCHMARK_DIR = Path(__file__).resolve().parents[1] / "benchmark" / "ocr"
sys.path.insert(0, str(OCR_BENCHMARK_DIR))

from benchlib import (  # noqa: E402
    BenchmarkError,
    bootstrap_cer_delta,
    edit_counts,
    load_json,
    normalize_text,
    percentile,
    select_samples,
    validate_manifest,
)
from runner import compare_results  # noqa: E402


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
    assert manifest["sample_files"] == ["project-egg.json"]
    assert len(manifest["samples"]) == 105
    assert len(select_samples(manifest)) == 100
    assert len(select_samples(manifest, suites=["legacy-smoke", "retro-real", "retro-pc"])) == 96
    assert len(select_samples(manifest, include_unscored=True)) == 105
    assert {sample["source"]["kind"] for sample in manifest["samples"]} <= {"url", "git"}
    assert all("synthetic" not in sample["id"] for sample in manifest["samples"])
    assert all("synthetic" not in sample["suites"] for sample in manifest["samples"])
    assert all("community-issue" not in sample["tags"] for sample in manifest["samples"])

    project_egg = [sample for sample in manifest["samples"] if "retro-pc" in sample["suites"]]
    assert len(project_egg) == 68
    assert {sample["annotation"]["status"] for sample in project_egg} == {"single_review"}
    assert {sample["source"]["author"] for sample in project_egg} == {"Project EGG / D4 Enterprise"}

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


def _comparison_report(sample_ids: list[str], **configuration_overrides: object) -> dict:
    configuration = {
        "pipeline": "src/interpreter/ocr.py::OCR.extract_text_regions",
        "join": "single ASCII space between non-empty regions",
        "confidence_threshold": 0.3,
        "repeats": 5,
        "warmups": 1,
        "seed": 1729,
        "suite_filter": ["real"],
        "role_filter": [],
        "include_unscored": False,
        **configuration_overrides,
    }
    return {
        "schema_version": 1,
        "configuration": configuration,
        "corpus": {
            "manifest_sha256": "manifest",
            "local_files": {
                sample_id: {"sha256": f"hash-{sample_id}", "width": 320, "height": 240} for sample_id in sample_ids
            },
        },
        "application": {"ocr_source_sha256": "ocr-source"},
        "samples": [{"id": sample_id} for sample_id in sample_ids],
    }


def test_compare_rejects_different_workload_configuration() -> None:
    baseline = _comparison_report(["one"], repeats=5)
    candidate = _comparison_report(["one"], repeats=3)

    with pytest.raises(BenchmarkError, match="different workload configuration: repeats"):
        compare_results(baseline, candidate)


def test_compare_rejects_unknown_future_workload_difference() -> None:
    baseline = _comparison_report(["one"])
    candidate = _comparison_report(["one"], future_option=True)

    with pytest.raises(BenchmarkError, match="different workload configuration: future_option"):
        compare_results(baseline, candidate)


def test_compare_rejects_different_selected_samples() -> None:
    baseline = _comparison_report(["one", "two"])
    candidate = _comparison_report(["one", "three"])

    with pytest.raises(BenchmarkError, match="different selected sample IDs"):
        compare_results(baseline, candidate)


def test_compare_rejects_different_local_corpus_files() -> None:
    baseline = _comparison_report(["one"])
    candidate = _comparison_report(["one"])
    candidate["corpus"]["local_files"]["one"]["sha256"] = "different-image"

    with pytest.raises(BenchmarkError, match="different local corpus files: one"):
        compare_results(baseline, candidate)
