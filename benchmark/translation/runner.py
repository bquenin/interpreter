"""Execute pinned translation models against an identical frozen workload."""

from __future__ import annotations

import os
import platform
import random
import statistics
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

from adapters import create_adapter, environment_package_versions
from benchlib import (
    BenchmarkError,
    fingerprint,
    has_japanese,
    latency_summary,
    modal_prediction,
    number_preservation,
    percentile,
    select_samples,
    sha256_file,
    stable_rank,
)


def _git_metadata(repo_root: Path) -> dict[str, Any]:
    def command(*args: str) -> str | None:
        try:
            return subprocess.check_output(["git", *args], cwd=repo_root, text=True, stderr=subprocess.DEVNULL).strip()
        except (OSError, subprocess.CalledProcessError):
            return None

    dirty = command("status", "--porcelain", "--untracked-files=no")
    translate_path = repo_root / "src" / "interpreter" / "translate.py"
    worker_path = repo_root / "src" / "interpreter" / "gui" / "workers.py"
    return {
        "commit": command("rev-parse", "HEAD"),
        "branch": command("branch", "--show-current"),
        "tracked_files_dirty": bool(dirty),
        "translate_source_sha256": sha256_file(translate_path),
        "worker_source_sha256": sha256_file(worker_path),
    }


def _benchmark_source_metadata(benchmark_dir: Path) -> dict[str, str]:
    names = ("adapters.py", "benchlib.py", "benchmark.py", "corpus.py", "runner.py")
    return {name: sha256_file(benchmark_dir / name) for name in names}


def _selected_identity(samples: list[dict[str, Any]]) -> str:
    fields = (
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
    return fingerprint([{field: sample[field] for field in fields} for sample in samples])


def _limit_samples(samples: list[dict[str, Any]], limit: int | None, seed: int) -> list[dict[str, Any]]:
    if limit is None:
        return samples
    if limit < 1:
        raise BenchmarkError("limit must be at least 1")
    ranked = sorted(samples, key=lambda item: (stable_rank(f"smoke-{seed}", item["id"]), item["id"]))
    chosen = {sample["id"] for sample in ranked[:limit]}
    return [sample for sample in samples if sample["id"] in chosen]


def summarize_runtime(samples: list[dict[str, Any]]) -> dict[str, Any]:
    numeric_preserved = numeric_total = 0
    length_ratios = []
    for sample in samples:
        preserved, total = number_preservation(sample["source"], sample.get("prediction", ""))
        numeric_preserved += preserved
        numeric_total += total
        source_length = len(sample["source"].replace(" ", ""))
        if source_length:
            length_ratios.append(len(sample.get("prediction", "")) / source_length)
    return {
        "samples": len(samples),
        "errors": sum(bool(sample.get("errors")) for sample in samples),
        "empty_predictions": sum(not sample.get("prediction", "").strip() for sample in samples),
        "japanese_leakage": sum(has_japanese(sample.get("prediction")) for sample in samples),
        "nondeterministic_samples": sum(sample.get("unique_predictions", 0) > 1 for sample in samples),
        "number_preservation": {
            "preserved": numeric_preserved,
            "total": numeric_total,
            "rate": numeric_preserved / numeric_total if numeric_total else None,
        },
        "output_source_length_ratio_median": statistics.median(length_ratios) if length_ratios else None,
        "latency_ms": latency_summary(samples),
    }


def _summaries(samples: list[dict[str, Any]]) -> dict[str, Any]:
    dimensions = {}
    for field in ("track", "game", "platform", "text_type", "length_bucket"):
        dimensions[field] = {
            value: summarize_runtime([sample for sample in samples if sample[field] == value])
            for value in sorted({sample[field] for sample in samples})
        }
    return {"overall": summarize_runtime(samples), "by": dimensions}


def run_benchmark(
    *,
    lock: dict[str, Any],
    lock_path: Path,
    model_registry: dict[str, Any],
    model_registry_path: Path,
    model_id: str,
    repo_root: Path,
    label: str | None,
    tracks: list[str] | None,
    games: list[str] | None,
    text_types: list[str] | None,
    repeats: int,
    warmups: int,
    seed: int,
    limit: int | None,
    device: str,
) -> dict[str, Any]:
    if repeats < 1:
        raise BenchmarkError("repeats must be at least 1")
    if warmups < 0:
        raise BenchmarkError("warmups cannot be negative")
    models = model_registry.get("models", {})
    if model_id not in models:
        raise BenchmarkError(f"Unknown model ID {model_id}; choose from {', '.join(sorted(models))}")

    selected = select_samples(lock, tracks=tracks, games=games, text_types=text_types)
    selected = _limit_samples(selected, limit, seed)
    if not selected:
        raise BenchmarkError("No corpus samples matched the requested filters")

    model = models[model_id]
    adapter = create_adapter(model_id, model, repo_root, device, seed)
    print(f"loading {model['label']} ({model['repo_id']}@{model['revision']})", flush=True)
    load_started = time.perf_counter()
    adapter.load()
    adapter.synchronize()
    load_ms = (time.perf_counter() - load_started) * 1000
    print(f"loaded on {adapter.device} in {load_ms:.1f} ms", flush=True)

    if warmups:
        warmup_sample = selected[0]
        for _ in range(warmups):
            adapter.clear_cache()
            adapter.translate(warmup_sample["source"])
            adapter.synchronize()

    accumulators = {sample["id"]: {"predictions": [], "latencies_ms": [], "errors": []} for sample in selected}
    rng = random.Random(seed)
    for repeat in range(repeats):
        order = list(selected)
        rng.shuffle(order)
        print(f"repeat {repeat + 1}/{repeats}", flush=True)
        for index, sample in enumerate(order, start=1):
            accumulator = accumulators[sample["id"]]
            adapter.clear_cache()
            adapter.synchronize()
            started = time.perf_counter()
            try:
                prediction = adapter.translate(sample["source"])
                adapter.synchronize()
                elapsed_ms = (time.perf_counter() - started) * 1000
                accumulator["predictions"].append(prediction)
                accumulator["latencies_ms"].append(elapsed_ms)
            except Exception as exc:  # Keep failed cases paired and auditable.
                try:
                    adapter.synchronize()
                except Exception:
                    pass
                elapsed_ms = (time.perf_counter() - started) * 1000
                if "out of memory" in str(exc).casefold():
                    raise BenchmarkError(f"{model_id} exhausted memory on {sample['id']}: {exc}") from exc
                accumulator["latencies_ms"].append(elapsed_ms)
                accumulator["errors"].append(f"{type(exc).__name__}: {exc}")
            if index == 1 or index % 25 == 0 or index == len(order):
                print(
                    f"  [{index:03d}/{len(order):03d}] {sample['id']} {accumulator['latencies_ms'][-1]:.1f} ms",
                    flush=True,
                )

    results = []
    for sample in selected:
        accumulator = accumulators[sample["id"]]
        predictions = accumulator["predictions"]
        variants = Counter(predictions)
        result = {
            key: sample[key]
            for key in (
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
        }
        result.update(
            {
                "prediction": modal_prediction(predictions),
                "prediction_variants": dict(variants),
                "unique_predictions": len(variants),
                "latencies_ms": accumulator["latencies_ms"],
                "latency_median_ms": percentile(accumulator["latencies_ms"], 0.5),
                "errors": accumulator["errors"],
            }
        )
        results.append(result)

    benchmark_dir = Path(__file__).resolve().parent
    workload = {
        "input_contract": "one exact player-visible Japanese text unit per translation call",
        "cache_policy": "clear application translation cache before every measured call",
        "sample_order": "same deterministic shuffled order for every model and repeat",
        "tracks": sorted(tracks or []),
        "games": sorted(games or []),
        "text_types": sorted(text_types or []),
        "repeats": repeats,
        "warmups": warmups,
        "seed": seed,
        "limit": limit,
        "device_preference": device,
    }
    return {
        "schema_version": 1,
        "label": label or model["label"],
        "model_id": model_id,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "configuration": workload,
        "corpus": {
            "lock": str(lock_path.resolve()),
            "lock_sha256": fingerprint(lock),
            "source_registry_sha256": lock["source_registry_sha256"],
            "reviews_sha256": lock["reviews_sha256"],
            "selected_identity_sha256": _selected_identity(selected),
            "selected_samples": len(selected),
        },
        "model_registry": {
            "path": str(model_registry_path.resolve()),
            "sha256": fingerprint(model_registry),
        },
        "application": _git_metadata(repo_root),
        "benchmark_sources": _benchmark_source_metadata(benchmark_dir),
        "environment": {
            "python": sys.version,
            "executable": sys.executable,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "packages": environment_package_versions(model),
            "hf_home": os.environ.get("HF_HOME"),
            "hf_hub_offline": os.environ.get("HF_HUB_OFFLINE"),
        },
        "model": adapter.metadata(),
        "model_load_ms": load_ms,
        "summary": _summaries(results),
        "samples": results,
    }
