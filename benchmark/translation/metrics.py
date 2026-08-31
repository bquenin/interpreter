"""Standard MT scoring and fail-closed paired model comparison."""

from __future__ import annotations

import copy
import importlib.metadata
import statistics
import time
from pathlib import Path
from typing import Any

from benchlib import (
    BenchmarkError,
    bootstrap_mean_delta,
    comparison_text,
    fingerprint,
    has_japanese,
    latency_summary,
    number_preservation,
    sha256_file,
)

COMET_REPO_ID = "Unbabel/wmt22-comet-da"
COMET_REVISION = "2760a223ac957f30acfb18c8aa649b01cf1d75f2"
COMET_ENCODER_REPO_ID = "xlm-roberta-large"
COMET_ENCODER_REVISION = "c23d21b0620b635a76227c604d44e43a9f0ee389"


def _scoring_source_metadata() -> dict[str, str]:
    directory = Path(__file__).resolve().parent
    return {name: sha256_file(directory / name) for name in ("benchlib.py", "metrics.py")}


def _sacrebleu_metrics():
    try:
        import sacrebleu
        from sacrebleu.metrics import BLEU, CHRF
    except ImportError as exc:
        raise BenchmarkError(
            "Scoring requires sacrebleu==2.5.1. Use the documented uv isolated score/compare command."
        ) from exc
    return sacrebleu, BLEU(effective_order=True), CHRF(word_order=2)


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _score_samples(samples: list[dict[str, Any]]) -> tuple[Any, Any, Any]:
    sacrebleu, bleu, chrf = _sacrebleu_metrics()
    for sample in samples:
        prediction = sample.get("prediction", "")
        references = sample["references"]
        comet = sample.get("metrics", {}).get("comet")
        sample["metrics"] = {
            "chrfpp": chrf.sentence_score(prediction, references).score,
            "bleu": bleu.sentence_score(prediction, references).score,
            "exact_reference_match": any(
                comparison_text(prediction) == comparison_text(reference) for reference in references
            ),
        }
        if comet is not None:
            sample["metrics"]["comet"] = comet
    return sacrebleu, bleu, chrf


def _slice_summary(samples: list[dict[str, Any]], bleu: Any, chrf: Any) -> dict[str, Any]:
    if not samples:
        return {"samples": 0, "macro_sentence_chrfpp": None, "corpus_chrfpp": None, "corpus_bleu": None}
    predictions = [sample.get("prediction", "") for sample in samples]
    primary_references = [[sample["references"][0] for sample in samples]]
    numeric_preserved = numeric_total = 0
    for sample in samples:
        preserved, total = number_preservation(sample["source"], sample.get("prediction", ""))
        numeric_preserved += preserved
        numeric_total += total
    comet_values = [sample["metrics"]["comet"] for sample in samples if "comet" in sample["metrics"]]
    return {
        "samples": len(samples),
        "macro_sentence_chrfpp": statistics.fmean(sample["metrics"]["chrfpp"] for sample in samples),
        "macro_sentence_bleu": statistics.fmean(sample["metrics"]["bleu"] for sample in samples),
        "corpus_chrfpp": chrf.corpus_score(predictions, primary_references).score,
        "corpus_bleu": bleu.corpus_score(predictions, primary_references).score,
        "comet": statistics.fmean(comet_values) if len(comet_values) == len(samples) else None,
        "exact_reference_matches": sum(sample["metrics"]["exact_reference_match"] for sample in samples),
        "errors": sum(bool(sample.get("errors")) for sample in samples),
        "empty_predictions": sum(not sample.get("prediction", "").strip() for sample in samples),
        "japanese_leakage": sum(has_japanese(sample.get("prediction")) for sample in samples),
        "nondeterministic_samples": sum(sample.get("unique_predictions", 0) > 1 for sample in samples),
        "number_preservation": {
            "preserved": numeric_preserved,
            "total": numeric_total,
            "rate": numeric_preserved / numeric_total if numeric_total else None,
        },
        "latency_ms": latency_summary(samples),
    }


def _summaries(samples: list[dict[str, Any]], bleu: Any, chrf: Any) -> dict[str, Any]:
    dimensions = {}
    for field in ("track", "game", "platform", "text_type", "length_bucket"):
        dimensions[field] = {
            value: _slice_summary([sample for sample in samples if sample[field] == value], bleu, chrf)
            for value in sorted({sample[field] for sample in samples})
        }
    return {"overall": _slice_summary(samples, bleu, chrf), "by": dimensions}


def _load_comet():
    try:
        import torch
        from comet import load_from_checkpoint
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise BenchmarkError(
            "COMET scoring requires unbabel-comet and huggingface-hub in the isolated metric environment"
        ) from exc
    model_dir = Path(
        snapshot_download(
            repo_id=COMET_REPO_ID,
            revision=COMET_REVISION,
            allow_patterns=["checkpoints/model.ckpt", "hparams.yaml"],
        )
    )
    encoder_dir = Path(
        snapshot_download(
            repo_id=COMET_ENCODER_REPO_ID,
            revision="main",
            allow_patterns=[
                "config.json",
                "sentencepiece.bpe.model",
                "tokenizer.json",
                "tokenizer_config.json",
            ],
        )
    )
    if encoder_dir.name != COMET_ENCODER_REVISION:
        raise BenchmarkError(
            f"{COMET_ENCODER_REPO_ID} main resolved to {encoder_dir.name}; expected {COMET_ENCODER_REVISION}"
        )
    checkpoint = model_dir / "checkpoints" / "model.ckpt"
    model = load_from_checkpoint(str(checkpoint), local_files_only=True)
    return torch, model, model_dir, encoder_dir


def _comet_scores(model: Any, torch: Any, samples: list[dict[str, Any]], batch_size: int) -> list[float]:
    data = [
        {"src": sample["source"], "mt": sample.get("prediction", ""), "ref": sample["references"][0]}
        for sample in samples
    ]
    prediction = model.predict(data, batch_size=batch_size, gpus=1 if torch.cuda.is_available() else 0)
    scores = getattr(prediction, "scores", None)
    if scores is None and isinstance(prediction, tuple):
        scores = prediction[0]
    if scores is None:
        raise BenchmarkError("COMET returned an unrecognized prediction object")
    output = [float(value) for value in scores]
    if len(output) != len(samples):
        raise BenchmarkError(f"COMET returned {len(output)} scores for {len(samples)} samples")
    return output


def score_results(
    results: list[dict[str, Any]],
    *,
    include_comet: bool = False,
    comet_batch_size: int = 16,
) -> list[dict[str, Any]]:
    """Score one or more raw results, sharing a single optional COMET load."""

    scored = [copy.deepcopy(result) for result in results]
    versions: dict[str, Any] = {}
    for result in scored:
        if result.get("schema_version") != 1 or not isinstance(result.get("samples"), list):
            raise BenchmarkError("Result is not a translation benchmark schema-v1 report")
        sacrebleu, bleu, chrf = _score_samples(result["samples"])
        versions = {
            "sacrebleu": getattr(sacrebleu, "__version__", _package_version("sacrebleu")),
            "bleu_signature": str(bleu.get_signature()),
            "chrfpp_signature": str(chrf.get_signature()),
        }

    comet_metadata = None
    if include_comet:
        torch, comet_model, model_dir, encoder_dir = _load_comet()
        for result in scored:
            values = _comet_scores(comet_model, torch, result["samples"], comet_batch_size)
            for sample, value in zip(result["samples"], values, strict=True):
                sample["metrics"]["comet"] = value
        comet_metadata = {
            "repo_id": COMET_REPO_ID,
            "revision": COMET_REVISION,
            "resolved_revision": model_dir.name,
            "encoder_repo_id": COMET_ENCODER_REPO_ID,
            "encoder_revision": COMET_ENCODER_REVISION,
            "encoder_resolved_revision": encoder_dir.name,
            "packages": {
                name: _package_version(name)
                for name in (
                    "unbabel-comet",
                    "torch",
                    "transformers",
                    "pytorch-lightning",
                    "torchmetrics",
                    "sentencepiece",
                    "huggingface-hub",
                )
            },
            "batch_size": comet_batch_size,
            "device": "cuda" if torch.cuda.is_available() else "cpu",
        }

    for result in scored:
        _, bleu, chrf = _sacrebleu_metrics()
        result["metrics"] = {
            "scored_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "source_sha256": sha256_file(Path(__file__)),
            "source_files_sha256": _scoring_source_metadata(),
            "primary": "macro mean of per-sample chrF++ against all available references",
            "secondary": "first-reference corpus chrF++ and BLEU; optional reference-based COMET",
            "versions": versions,
            "comet": comet_metadata,
            "summary": _summaries(result["samples"], bleu, chrf),
        }
    return scored


_WORKLOAD_FIELDS = (
    "input_contract",
    "cache_policy",
    "sample_order",
    "tracks",
    "games",
    "text_types",
    "repeats",
    "warmups",
    "seed",
    "limit",
    "device_preference",
)


def _validate_comparison_contract(baseline: dict[str, Any], candidate: dict[str, Any]) -> None:
    for label, result in (("Baseline", baseline), ("Candidate", candidate)):
        if result.get("schema_version") != 1:
            raise BenchmarkError(f"{label} report does not use schema version 1")
        if not isinstance(result.get("samples"), list) or not result["samples"]:
            raise BenchmarkError(f"{label} report has no samples")
        configuration = result.get("configuration")
        if not isinstance(configuration, dict):
            raise BenchmarkError(f"{label} report has no workload configuration")
        missing = [field for field in _WORKLOAD_FIELDS if field not in configuration]
        if missing:
            raise BenchmarkError(f"{label} workload is missing: {', '.join(missing)}")

    checks = {
        "corpus lock": (baseline["corpus"].get("lock_sha256"), candidate["corpus"].get("lock_sha256")),
        "selected corpus identity": (
            baseline["corpus"].get("selected_identity_sha256"),
            candidate["corpus"].get("selected_identity_sha256"),
        ),
        "source registry": (
            baseline["corpus"].get("source_registry_sha256"),
            candidate["corpus"].get("source_registry_sha256"),
        ),
        "reference reviews": (
            baseline["corpus"].get("reviews_sha256"),
            candidate["corpus"].get("reviews_sha256"),
        ),
        "model registry": (
            baseline["model_registry"].get("sha256"),
            candidate["model_registry"].get("sha256"),
        ),
        "production translation source": (
            baseline["application"].get("translate_source_sha256"),
            candidate["application"].get("translate_source_sha256"),
        ),
        "production worker source": (
            baseline["application"].get("worker_source_sha256"),
            candidate["application"].get("worker_source_sha256"),
        ),
        "benchmark runner sources": (
            fingerprint(baseline.get("benchmark_sources")),
            fingerprint(candidate.get("benchmark_sources")),
        ),
        "workload": (fingerprint(baseline["configuration"]), fingerprint(candidate["configuration"])),
    }
    changed = [name for name, (first, second) in checks.items() if not first or first != second]
    if changed:
        raise BenchmarkError(f"Cannot compare reports with different {', '.join(changed)}")

    identity_fields = (
        "id",
        "pair_id",
        "source_id",
        "game",
        "platform",
        "release_year",
        "genre",
        "text_type",
        "length_bucket",
        "track",
        "source",
        "references",
        "reference_status",
        "independently_verified",
        "provenance",
    )
    baseline_records = [{field: sample.get(field) for field in identity_fields} for sample in baseline["samples"]]
    candidate_records = [{field: sample.get(field) for field in identity_fields} for sample in candidate["samples"]]
    if baseline_records != candidate_records:
        raise BenchmarkError("Cannot compare reports whose ordered sample records differ")

    baseline_has_comet = any("comet" in sample.get("metrics", {}) for sample in baseline["samples"])
    candidate_has_comet = any("comet" in sample.get("metrics", {}) for sample in candidate["samples"])
    if baseline_has_comet != candidate_has_comet:
        raise BenchmarkError("Cannot compare reports when only one contains COMET sample scores")
    if baseline_has_comet:
        baseline_comet = baseline.get("metrics", {}).get("comet")
        candidate_comet = candidate.get("metrics", {}).get("comet")
        if not baseline_comet or fingerprint(baseline_comet) != fingerprint(candidate_comet):
            raise BenchmarkError("Cannot compare reports scored with different COMET configurations")


def _outcome(paired: dict[str, Any]) -> str:
    delta = paired["delta"]
    lower, upper = paired["ci95"]
    if delta is None or lower is None or upper is None:
        return "inconclusive"
    if lower > 0:
        return "candidate_better"
    if upper < 0:
        return "candidate_worse"
    if lower == upper == 0:
        return "tied"
    return "inconclusive"


def _score_map(samples: list[dict[str, Any]], metric: str, *, track: str = "screen") -> dict[str, float]:
    return {
        sample["id"]: float(sample["metrics"][metric])
        for sample in samples
        if sample["track"] == track and metric in sample["metrics"]
    }


def _wins(baseline: dict[str, float], candidate: dict[str, float]) -> dict[str, int]:
    wins = losses = ties = 0
    for sample_id in baseline.keys() & candidate.keys():
        difference = candidate[sample_id] - baseline[sample_id]
        if difference > 1e-12:
            wins += 1
        elif difference < -1e-12:
            losses += 1
        else:
            ties += 1
    return {"candidate_wins": wins, "candidate_losses": losses, "ties": ties}


def _blind_review_summary(review: dict[str, Any] | None, baseline_id: str, candidate_id: str) -> dict[str, Any]:
    if review is None:
        return {
            "judgments": 0,
            "candidate_wins": 0,
            "baseline_wins": 0,
            "ties": 0,
            "candidate_win_rate": None,
            "candidate_win_rate_ci95": [None, None],
        }
    if review.get("schema_version") != 1:
        raise BenchmarkError("Blind review report does not use schema version 1")
    models = review.get("models")
    if set(models or []) != {baseline_id, candidate_id}:
        raise BenchmarkError("Blind review report was created for different models")
    return {
        key: review.get(key)
        for key in (
            "judgments",
            "candidate_wins",
            "baseline_wins",
            "ties",
            "candidate_win_rate",
            "candidate_win_rate_ci95",
        )
    }


def compare_results(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    bootstrap_iterations: int = 10_000,
    bootstrap_seed: int = 1729,
    min_verified_pairs: int = 100,
    min_games: int = 5,
    min_blind_judgments: int = 100,
    max_p95_ms: float = 750.0,
    max_latency_ratio: float = 10.0,
    max_artifact_gib: float = 5.0,
    max_artifact_ratio: float = 4.0,
    max_game_regression: float = 2.0,
    blind_review: dict[str, Any] | None = None,
    private_holdout_passed: bool = False,
    license_approved: bool = False,
) -> dict[str, Any]:
    _validate_comparison_contract(baseline, candidate)
    baseline, candidate = score_results([baseline, candidate], include_comet=False)

    baseline_screen = _score_map(baseline["samples"], "chrfpp")
    candidate_screen = _score_map(candidate["samples"], "chrfpp")
    paired = bootstrap_mean_delta(
        baseline_screen,
        candidate_screen,
        iterations=bootstrap_iterations,
        seed=bootstrap_seed,
    )
    outcome = _outcome(paired)
    wins = _wins(baseline_screen, candidate_screen)

    paired_comet = None
    baseline_comet = _score_map(baseline["samples"], "comet")
    candidate_comet = _score_map(candidate["samples"], "comet")
    if baseline_comet and baseline_comet.keys() == candidate_comet.keys():
        paired_comet = bootstrap_mean_delta(
            baseline_comet,
            candidate_comet,
            iterations=bootstrap_iterations,
            seed=bootstrap_seed,
        )

    baseline_summary = baseline["metrics"]["summary"]
    candidate_summary = candidate["metrics"]["summary"]
    baseline_primary = baseline_summary["by"]["track"]["screen"]
    candidate_primary = candidate_summary["by"]["track"]["screen"]

    baseline_p95 = baseline_primary["latency_ms"]["p95"]
    candidate_p95 = candidate_primary["latency_ms"]["p95"]
    latency_ratio = candidate_p95 / baseline_p95 if baseline_p95 and candidate_p95 is not None else None
    baseline_bytes = baseline["model"]["artifacts"]["bytes"]
    candidate_bytes = candidate["model"]["artifacts"]["bytes"]
    artifact_ratio = candidate_bytes / baseline_bytes if baseline_bytes else None

    by_game = {}
    regressed_games = []
    games = sorted({sample["game"] for sample in baseline["samples"] if sample["track"] == "screen"})
    for game in games:
        first = {
            sample["id"]: sample["metrics"]["chrfpp"]
            for sample in baseline["samples"]
            if sample["track"] == "screen" and sample["game"] == game
        }
        second = {
            sample["id"]: sample["metrics"]["chrfpp"]
            for sample in candidate["samples"]
            if sample["track"] == "screen" and sample["game"] == game
        }
        game_paired = bootstrap_mean_delta(first, second, iterations=bootstrap_iterations, seed=bootstrap_seed)
        by_game[game] = game_paired
        if game_paired["delta"] is not None and game_paired["delta"] < -max_game_regression:
            regressed_games.append(game)

    verified = [
        sample for sample in baseline["samples"] if sample["track"] == "screen" and sample["independently_verified"]
    ]
    verified_games = {sample["game"] for sample in verified}
    review_summary = _blind_review_summary(blind_review, baseline["model_id"], candidate["model_id"])

    blockers = []
    if outcome != "candidate_better":
        blockers.append(f"paired screen-track chrF++ outcome is {outcome}, not candidate_better")
    if candidate_primary["errors"]:
        blockers.append(f"candidate had {candidate_primary['errors']} screen-track sample errors")
    if candidate_primary["empty_predictions"]:
        blockers.append(f"candidate returned {candidate_primary['empty_predictions']} empty screen translations")
    if candidate_primary["nondeterministic_samples"]:
        blockers.append(
            f"candidate produced multiple outputs for {candidate_primary['nondeterministic_samples']} screen samples"
        )
    leakage_tolerance = max(1, round(candidate_primary["samples"] * 0.01))
    if candidate_primary["japanese_leakage"] > baseline_primary["japanese_leakage"] + leakage_tolerance:
        blockers.append("candidate Japanese-text leakage regressed by more than one percentage point")
    baseline_numbers = baseline_primary["number_preservation"]["rate"]
    candidate_numbers = candidate_primary["number_preservation"]["rate"]
    if baseline_numbers is not None and (candidate_numbers is None or candidate_numbers < baseline_numbers - 0.02):
        blockers.append("candidate numeric-token preservation regressed by more than two percentage points")
    if candidate_p95 is None or candidate_p95 > max_p95_ms:
        blockers.append(f"candidate screen p95 latency must be at most {max_p95_ms:.0f} ms")
    if latency_ratio is None or latency_ratio > max_latency_ratio:
        blockers.append(f"candidate screen p95 latency exceeds {max_latency_ratio:.1f}x baseline")
    if candidate_bytes > max_artifact_gib * 1024**3:
        blockers.append(f"candidate artifacts exceed {max_artifact_gib:.1f} GiB")
    if artifact_ratio is None or artifact_ratio > max_artifact_ratio:
        blockers.append(f"candidate artifacts exceed {max_artifact_ratio:.1f}x baseline size")
    if regressed_games:
        blockers.append(
            f"candidate regressed by more than {max_game_regression:.1f} chrF++ on: {', '.join(regressed_games)}"
        )
    if len(verified) < min_verified_pairs:
        blockers.append(f"only {len(verified)} independently verified pairs; require {min_verified_pairs}")
    if len(verified_games) < min_games:
        blockers.append(f"verified references cover {len(verified_games)} games; require {min_games}")
    if review_summary["judgments"] is None or review_summary["judgments"] < min_blind_judgments:
        blockers.append(
            f"only {review_summary['judgments'] or 0} blind human preference judgments; require {min_blind_judgments}"
        )
    elif (
        not review_summary["candidate_win_rate_ci95"]
        or review_summary["candidate_win_rate_ci95"][0] is None
        or review_summary["candidate_win_rate_ci95"][0] <= 0.5
    ):
        blockers.append("blind human preference lower confidence bound does not exceed 50%")
    if not private_holdout_passed:
        blockers.append("no separately held private game-text evaluation has been recorded")
    if not license_approved:
        blockers.append(f"deployment license has not been approved: {candidate['model']['registry']['license']}")

    return {
        "schema_version": 1,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "baseline": {"model_id": baseline["model_id"], "label": baseline["label"]},
        "candidate": {"model_id": candidate["model_id"], "label": candidate["label"]},
        "primary_metric": "screen-track macro sentence chrF++ (higher is better)",
        "paired_chrfpp": paired,
        "paired_comet": paired_comet,
        "statistical_outcome": outcome,
        **wins,
        "baseline_summary": baseline_summary,
        "candidate_summary": candidate_summary,
        "latency_p95_ratio": latency_ratio,
        "artifact_size_ratio": artifact_ratio,
        "by_game": by_game,
        "blind_review": review_summary,
        "promotion_gate": {
            "ready": not blockers,
            "blockers": blockers,
            "verified_pairs": len(verified),
            "verified_games": len(verified_games),
            "requirements": {
                "min_verified_pairs": min_verified_pairs,
                "min_games": min_games,
                "min_blind_judgments": min_blind_judgments,
                "max_p95_ms": max_p95_ms,
                "max_latency_ratio": max_latency_ratio,
                "max_artifact_gib": max_artifact_gib,
                "max_artifact_ratio": max_artifact_ratio,
                "max_game_regression": max_game_regression,
                "private_holdout_passed": private_holdout_passed,
                "license_approved": license_approved,
            },
        },
    }


def format_scored_summary(result: dict[str, Any]) -> str:
    overall = result["metrics"]["summary"]["overall"]
    screen = result["metrics"]["summary"]["by"]["track"]["screen"]
    return (
        f"chrF++={screen['macro_sentence_chrfpp']:.2f} screen / "
        f"{overall['macro_sentence_chrfpp']:.2f} all, BLEU={screen['corpus_bleu']:.2f}, "
        f"p95={screen['latency_ms']['p95']:.1f} ms, errors={screen['errors']}"
    )
