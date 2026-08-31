"""Tests for the standalone translation benchmark tooling."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = ROOT / "benchmark" / "translation"
sys.path.insert(0, str(BENCHMARK_DIR))

# The standalone OCR benchmark deliberately has modules with the same names.
# Import this toolset as one temporary group, then restore any module that the
# OCR tests loaded during collection so both suites can share a pytest process.
_previous_benchlib = sys.modules.pop("benchlib", None)
try:
    import adapters
    import benchlib
    import corpus
    import metrics
    import review
finally:
    if _previous_benchlib is None:
        sys.modules.pop("benchlib", None)
    else:
        sys.modules["benchlib"] = _previous_benchlib


def _load(name: str) -> dict:
    return json.loads((BENCHMARK_DIR / name).read_text(encoding="utf-8"))


def test_registries_are_valid_and_models_are_revision_pinned():
    sources = _load("sources.json")
    models = _load("models.json")
    reviews = _load("reviews.json")

    assert benchlib.validate_source_registry(sources) == []
    assert benchlib.validate_model_registry(models) == []
    assert benchlib.validate_reviews(reviews) == []
    assert all(len(model["revision"]) == 40 for model in models["models"].values())
    assert (
        sum(
            quota
            for source in sources["sources"]
            for by_length in source["quotas"].values()
            for quota in by_length.values()
        )
        == 268
    )


def test_corpus_cleaning_removes_controls_but_preserves_visible_punctuation():
    raw = r"\LineWidthPortraitShowing/(CODE 21 Elina:) えっ(LINE)本当[！？]{82}(End quote)(STOP)"
    assert corpus._clean_metal(raw) == "えっ 本当！？"
    assert corpus._clean_phantasy("<line>アリサ<wait><player>") == ""
    assert corpus._clean_nintendo("悪事がある｜ 契約まで") == "悪事がある 契約まで"
    assert benchlib.has_japanese("・・・「!?」") is False
    assert benchlib.has_japanese("忠！！") is True

    screen_raw = "<X1e>セリオス<X04>こんにちは。<RETN>"
    reference_raw = "<X1e>Selios<X04>Hello.<RETN>"
    screen = corpus._clean_ds6(screen_raw)
    reference = corpus._clean_ds6(reference_raw)
    assert screen == "セリオス こんにちは。"
    assert reference == "Selios Hello."
    assert corpus._valid_ds6_record(screen_raw, reference_raw, screen, reference)
    assert not corpus._valid_ds6_record(
        "スライムさんが現れた。このファイルは Ｍ−０３６ です。<RETN>",
        "Slimey appears. This file is M-036.<RETN>",
        "スライムさんが現れた。このファイルは Ｍ−０３６ です。",
        "Slimey appears. This file is M-036.",
    )
    assert not corpus._valid_ds6_record(
        "<CALL123>は話した。",
        "<CALL123> spoke.",
        "は話した。",
        "spoke.",
    )
    assert not corpus._valid_ds6_record(
        "は 奇妙な かおりの花粉をふりまいた。<X0a>",
        " scatters its odd-smelling pollen.<X0a>",
        "は 奇妙な かおりの花粉をふりまいた。",
        "scatters its odd-smelling pollen.",
    )


def test_sampling_is_deterministic_and_stratified():
    registry = {
        "sampling_seed": "fixed",
        "sources": [
            {
                "id": "game",
                "quotas": {
                    "dialogue": {"short": 2, "medium": 0, "long": 0},
                },
            }
        ],
    }
    entries = [
        {
            "pair_id": f"game:{index}",
            "source_id": "game",
            "text_type": "dialogue",
            "length_bucket": "short",
        }
        for index in range(10)
    ]
    first = benchlib.select_entries(entries, registry)
    second = benchlib.select_entries(list(reversed(entries)), registry)
    assert [item["pair_id"] for item in first] == [item["pair_id"] for item in second]
    assert len(first) == 2


def test_only_blind_human_reference_reviews_count_as_verified():
    entry = {
        "pair_id": "game:1",
        "reference_status": "single_source_review",
    }
    reviews = {
        "reviews": {
            "game:1": {
                "status": "verified",
                "reviewer_kind": "human",
                "blind_to_model_outputs": True,
            }
        }
    }
    assert benchlib.apply_reviews([entry], reviews)[0]["independently_verified"] is True
    reviews["reviews"]["game:1"]["blind_to_model_outputs"] = False
    assert benchlib.apply_reviews([entry], reviews)[0]["independently_verified"] is False


def test_candidate_output_normalization_matches_production_contract():
    value = "  ‘one’ “two” – — −\u00a0…  "
    assert adapters.normalize_display_output(value) == "'one' \"two\" - -- - ..."


class _FakeMetric:
    def sentence_score(self, prediction, references):
        del references
        return SimpleNamespace(score={"baseline": 20.0, "candidate": 40.0}.get(prediction, 0.0))

    def corpus_score(self, predictions, references):
        del references
        values = [{"baseline": 20.0, "candidate": 40.0}.get(value, 0.0) for value in predictions]
        return SimpleNamespace(score=sum(values) / len(values))

    def get_signature(self):
        return "fake-signature"


def _result(model_id: str, prediction: str) -> dict:
    sample = {
        "id": "game:1::screen",
        "pair_id": "game:1",
        "source_id": "game",
        "game": "Game",
        "platform": "Console",
        "release_year": 1990,
        "genre": "role-playing game",
        "text_type": "dialogue",
        "length_bucket": "short",
        "track": "screen",
        "source": "こんにちは",
        "references": ["Hello"],
        "reference_status": "single_source_review",
        "independently_verified": False,
        "provenance": {"repository": "https://example.invalid"},
        "prediction": prediction,
        "prediction_variants": {prediction: 3},
        "unique_predictions": 1,
        "latencies_ms": [10.0, 11.0, 12.0],
        "latency_median_ms": 11.0,
        "errors": [],
    }
    configuration = {
        "input_contract": "unit",
        "cache_policy": "clear",
        "sample_order": "fixed",
        "tracks": [],
        "games": [],
        "text_types": [],
        "repeats": 3,
        "warmups": 2,
        "seed": 1729,
        "limit": None,
        "device_preference": "auto",
    }
    return {
        "schema_version": 1,
        "label": model_id,
        "model_id": model_id,
        "configuration": configuration,
        "corpus": {
            "lock_sha256": "lock",
            "selected_identity_sha256": "identity",
            "source_registry_sha256": "sources",
            "reviews_sha256": "reviews",
        },
        "model_registry": {"sha256": "models"},
        "application": {"translate_source_sha256": "translate", "worker_source_sha256": "worker"},
        "benchmark_sources": {"runner.py": "runner"},
        "model": {
            "registry": {"license": "review required"},
            "artifacts": {"bytes": 1_000_000},
        },
        "samples": [sample],
    }


@pytest.fixture
def fake_sacrebleu(monkeypatch):
    monkeypatch.setattr(
        metrics,
        "_sacrebleu_metrics",
        lambda: (SimpleNamespace(__version__="test"), _FakeMetric(), _FakeMetric()),
    )


def test_comparison_is_paired_and_promotion_stays_blocked_without_human_gates(fake_sacrebleu):
    comparison = metrics.compare_results(
        _result("production", "baseline"),
        _result("candidate-model", "candidate"),
        bootstrap_iterations=100,
    )
    assert comparison["statistical_outcome"] == "candidate_better"
    assert comparison["paired_chrfpp"]["delta"] == 20.0
    assert comparison["promotion_gate"]["ready"] is False
    blockers = " ".join(comparison["promotion_gate"]["blockers"])
    assert "independently verified" in blockers
    assert "blind human" in blockers
    assert "private" in blockers
    assert "license" in blockers


def test_comparison_rejects_changed_source_even_when_ids_match(fake_sacrebleu):
    baseline = _result("production", "baseline")
    candidate = _result("candidate-model", "candidate")
    candidate["samples"][0]["source"] = "さようなら"
    with pytest.raises(benchlib.BenchmarkError, match="sample records differ"):
        metrics.compare_results(baseline, candidate, bootstrap_iterations=10)


def test_comparison_rejects_mismatched_comet_configuration(fake_sacrebleu):
    baseline = _result("production", "baseline")
    candidate = _result("candidate-model", "candidate")
    for result, revision in ((baseline, "first"), (candidate, "second")):
        result["samples"][0]["metrics"] = {"comet": 0.5}
        result["metrics"] = {"comet": {"revision": revision}}
    with pytest.raises(benchlib.BenchmarkError, match="different COMET configurations"):
        metrics.compare_results(baseline, candidate, bootstrap_iterations=10)


def test_blind_packet_uses_separate_key_and_detects_mutation(tmp_path):
    baseline = _result("production", "baseline")
    candidate = _result("candidate-model", "candidate")
    packet = tmp_path / "packet.csv"
    key_path = tmp_path / "key.json"
    report = review.create_blind_packet(
        baseline,
        candidate,
        packet_path=packet,
        key_path=key_path,
    )
    assert report["rows"] == 1
    key = json.loads(key_path.read_text(encoding="utf-8"))
    with packet.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert "production" not in rows[0]["translation_a"] + rows[0]["translation_b"]
    rows[0]["preference"] = "A"
    with packet.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=review.REVIEW_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    scored = review.score_blind_packet(packet, key)
    assert scored["judgments"] == 1

    rows[0]["source"] = "changed"
    with packet.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=review.REVIEW_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(benchlib.BenchmarkError, match="changed after randomization"):
        review.score_blind_packet(packet, key)


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@"])
def test_blind_packet_escapes_formula_cells_without_changing_integrity(tmp_path, prefix):
    baseline = _result("production", f"{prefix}baseline")
    candidate = _result("candidate-model", f"{prefix}candidate")
    baseline["samples"][0]["source"] = f"{prefix}source"
    candidate["samples"][0]["source"] = f"{prefix}source"
    packet = tmp_path / "packet.csv"
    key_path = tmp_path / "key.json"

    review.create_blind_packet(baseline, candidate, packet_path=packet, key_path=key_path)
    key = json.loads(key_path.read_text(encoding="utf-8"))
    with packet.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert rows[0]["source"] == f"'{prefix}source"
    assert rows[0]["translation_a"].startswith(f"'{prefix}")
    assert rows[0]["translation_b"].startswith(f"'{prefix}")
    assert key["packet_fingerprint"] != key["export_fingerprint"]
    rows[0]["preference"] = "A"
    with packet.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=review.REVIEW_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    assert review.score_blind_packet(packet, key)["judgments"] == 1

    rows[0]["source"] = f"''{prefix}source"
    with packet.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=review.REVIEW_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(benchlib.BenchmarkError, match="changed after randomization"):
        review.score_blind_packet(packet, key)


def test_reference_packet_escapes_all_formula_prefixes(tmp_path):
    lock = {
        "pairs": [
            {
                "pair_id": "game:1",
                "game": "Game",
                "platform": "Console",
                "text_type": "dialogue",
                "length_bucket": "short",
                "screen": "=source",
                "normalized": "+normalized",
                "references": ["-reference", "@reference"],
            }
        ]
    }
    packet = tmp_path / "references.csv"

    assert review.create_reference_packet(lock, packet_path=packet) == 1
    with packet.open(encoding="utf-8-sig", newline="") as handle:
        row = next(csv.DictReader(handle))

    assert row["screen_source"] == "'=source"
    assert row["normalized_source"] == "'+normalized"
    assert row["reference_1"] == "'-reference"
    assert row["reference_2"] == "'@reference"
