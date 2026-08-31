"""Run the exact Interpreter OCR pipeline and compare paired results."""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import os
import platform
import random
import subprocess
import sys
import time
import types
from collections import Counter
from pathlib import Path
from typing import Any

from benchlib import (
    SCOREABLE_STATUSES,
    BenchmarkError,
    bootstrap_cer_delta,
    edit_counts,
    load_json,
    manifest_fingerprint,
    modal_prediction,
    percentile,
    select_samples,
    sha256_file,
    summarize_samples,
)


class _SilentLogger:
    def __getattr__(self, _name: str):
        return lambda *args, **kwargs: None


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise BenchmarkError(f"Could not load application module {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_application_ocr(repo_root: Path):
    """Load src/interpreter/ocr.py without importing GUI/capture backends.

    This preserves the production OCR and post-processing code while allowing
    it to run in a tiny isolated candidate environment containing only
    meikiocr and its dependencies.
    """

    source_root = repo_root / "src" / "interpreter"
    if not (source_root / "ocr.py").is_file():
        raise BenchmarkError(f"Interpreter OCR source not found under {repo_root}")

    package = types.ModuleType("interpreter")
    package.__path__ = [str(source_root)]
    sys.modules["interpreter"] = package

    capture_package = types.ModuleType("interpreter.capture")
    capture_package.__path__ = [str(source_root / "capture")]
    sys.modules["interpreter.capture"] = capture_package

    log_module = types.ModuleType("interpreter.log")
    log_module.get_logger = lambda *_args, **_kwargs: _SilentLogger()
    sys.modules["interpreter.log"] = log_module

    _load_module("interpreter.capture.convert", source_root / "capture" / "convert.py")
    ocr_module = _load_module("interpreter.ocr", source_root / "ocr.py")
    return ocr_module.OCR


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _model_file_metadata() -> list[dict[str, Any]]:
    try:
        meiki_module = importlib.import_module("meikiocr.ocr")
        from huggingface_hub import try_to_load_from_cache
    except (ImportError, ModuleNotFoundError):
        return []

    files = []
    for prefix in ("DET", "REC"):
        repo_id = getattr(meiki_module, f"{prefix}_MODEL_REPO", None)
        filename = getattr(meiki_module, f"{prefix}_MODEL_NAME", None)
        if not repo_id or not filename:
            continue
        cached = try_to_load_from_cache(repo_id, filename)
        entry: dict[str, Any] = {"role": prefix.lower(), "repo_id": repo_id, "filename": filename}
        if isinstance(cached, str):
            path = Path(cached)
            entry.update({"sha256": sha256_file(path), "bytes": path.stat().st_size})
            parts = path.parts
            if "snapshots" in parts:
                snapshot_index = parts.index("snapshots") + 1
                if snapshot_index < len(parts):
                    entry["snapshot"] = parts[snapshot_index]
        files.append(entry)
    return files


def _git_metadata(repo_root: Path) -> dict[str, Any]:
    def command(*args: str) -> str | None:
        try:
            return subprocess.check_output(["git", *args], cwd=repo_root, text=True).strip()
        except (OSError, subprocess.CalledProcessError):
            return None

    dirty = command("status", "--porcelain", "--untracked-files=no")
    return {
        "commit": command("rev-parse", "HEAD"),
        "branch": command("branch", "--show-current"),
        "tracked_files_dirty": bool(dirty),
        "ocr_source_sha256": sha256_file(repo_root / "src" / "interpreter" / "ocr.py"),
    }


def _read_bgra(path: Path):
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise BenchmarkError("The model environment must provide OpenCV and NumPy") from exc

    encoded = np.fromfile(path, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_UNCHANGED)
    if image is None:
        raise BenchmarkError(f"Could not decode image: {path}")
    if image.ndim == 2:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGRA)
    if image.shape[2] == 3:
        return cv2.cvtColor(image, cv2.COLOR_BGR2BGRA)
    if image.shape[2] == 4:
        return image
    raise BenchmarkError(f"Unsupported image shape for {path}: {image.shape}")


def _region_dict(region: Any) -> dict[str, Any]:
    return {"text": region.text, "bbox": region.bbox}


def run_benchmark(
    manifest: dict[str, Any],
    manifest_path: Path,
    data_dir: Path,
    repo_root: Path,
    label: str,
    suites: list[str] | None,
    roles: list[str] | None,
    repeats: int,
    warmups: int,
    seed: int,
    confidence: float,
    include_unscored: bool,
) -> dict[str, Any]:
    if repeats < 1:
        raise BenchmarkError("repeats must be at least 1")
    if warmups < 0:
        raise BenchmarkError("warmups cannot be negative")

    selected = select_samples(
        manifest,
        suites=suites,
        roles=roles,
        include_unscored=include_unscored,
    )
    if not selected:
        raise BenchmarkError("No scoreable corpus samples matched. Prepare annotations or use --include-unscored.")

    lock_path = data_dir / "corpus.lock.json"
    lock = load_json(lock_path)
    fingerprint = manifest_fingerprint(manifest)
    if lock.get("manifest_sha256") != fingerprint:
        raise BenchmarkError("Corpus lock does not match corpus.json; run the prepare command again")

    images = {}
    local_files = {}
    for sample in selected:
        local = lock.get("files", {}).get(sample["id"])
        if not local:
            raise BenchmarkError(
                f"Sample {sample['id']} is absent from corpus.lock.json; run prepare with the same filters"
            )
        path = (data_dir / sample["path"]).resolve()
        if not path.is_file():
            raise BenchmarkError(f"Missing corpus image: {path}")
        actual_hash = sha256_file(path)
        if actual_hash != local["sha256"]:
            raise BenchmarkError(f"Local corpus image changed since prepare: {sample['id']}")
        images[sample["id"]] = _read_bgra(path)
        local_files[sample["id"]] = {
            "sha256": actual_hash,
            "width": local["width"],
            "height": local["height"],
        }

    OCR = load_application_ocr(repo_root)
    ocr = OCR(confidence_threshold=confidence)
    load_started = time.perf_counter()
    ocr.load()
    load_ms = (time.perf_counter() - load_started) * 1000

    if warmups:
        warmup_image = images[selected[0]["id"]]
        for _ in range(warmups):
            ocr.extract_text_regions(warmup_image)

    accumulators = {
        sample["id"]: {"predictions": [], "latencies_ms": [], "regions": None, "error": None} for sample in selected
    }
    rng = random.Random(seed)
    for repeat in range(repeats):
        order = list(selected)
        rng.shuffle(order)
        print(f"repeat {repeat + 1}/{repeats}")
        for index, sample in enumerate(order, start=1):
            accumulator = accumulators[sample["id"]]
            started = time.perf_counter()
            try:
                regions = ocr.extract_text_regions(images[sample["id"]])
                elapsed_ms = (time.perf_counter() - started) * 1000
                prediction = " ".join(region.text for region in regions if region.text)
                accumulator["predictions"].append(prediction)
                accumulator["latencies_ms"].append(elapsed_ms)
                if accumulator["regions"] is None:
                    accumulator["regions"] = [_region_dict(region) for region in regions]
            except Exception as exc:  # Preserve a failed sample in the report.
                elapsed_ms = (time.perf_counter() - started) * 1000
                accumulator["latencies_ms"].append(elapsed_ms)
                accumulator["error"] = f"{type(exc).__name__}: {exc}"
            print(f"  [{index:02d}/{len(order):02d}] {sample['id']} {accumulator['latencies_ms'][-1]:.1f} ms")

    results = []
    for sample in selected:
        accumulator = accumulators[sample["id"]]
        prediction = modal_prediction(accumulator["predictions"])
        status = sample["annotation"]["status"]
        reference = sample["annotation"].get("text") if status in SCOREABLE_STATUSES else None
        counts = edit_counts(reference, prediction) if reference is not None and not accumulator["error"] else None
        variants = Counter(accumulator["predictions"])
        results.append(
            {
                "id": sample["id"],
                "path": sample["path"],
                "game": sample.get("game"),
                "role": sample["role"],
                "suites": sample["suites"],
                "tags": sample.get("tags", []),
                "annotation_status": status,
                "reference": reference,
                "prediction": prediction,
                "prediction_variants": dict(variants),
                "unique_predictions": len(variants),
                "counts": counts,
                "latencies_ms": accumulator["latencies_ms"],
                "latency_median_ms": percentile(accumulator["latencies_ms"], 0.5),
                "regions": accumulator["regions"],
                "error": accumulator["error"],
            }
        )

    by_suite = {}
    for suite in sorted({suite for sample in results for suite in sample["suites"]}):
        by_suite[suite] = summarize_samples([sample for sample in results if suite in sample["suites"]])
    by_role = {}
    for role in sorted({sample["role"] for sample in results}):
        by_role[role] = summarize_samples([sample for sample in results if sample["role"] == role])

    model = getattr(ocr, "_model", None)
    active_provider = getattr(model, "active_provider", None)
    provider_stack = None
    if model is not None and getattr(model, "det_session", None) is not None:
        provider_stack = model.det_session.get_providers()

    return {
        "schema_version": 1,
        "label": label,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "configuration": {
            "pipeline": "src/interpreter/ocr.py::OCR.extract_text_regions",
            "join": "single ASCII space between non-empty regions",
            "confidence_threshold": confidence,
            "repeats": repeats,
            "warmups": warmups,
            "seed": seed,
            "suite_filter": suites or [],
            "role_filter": roles or [],
            "include_unscored": include_unscored,
        },
        "corpus": {
            "manifest": str(manifest_path.resolve()),
            "manifest_sha256": fingerprint,
            "local_files": local_files,
        },
        "application": _git_metadata(repo_root),
        "environment": {
            "python": sys.version,
            "executable": sys.executable,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "packages": {
                name: _package_version(name)
                for name in ("meikiocr", "onnxruntime", "numpy", "opencv-python", "opencv-python-headless")
            },
            "onnx_active_provider": active_provider,
            "onnx_provider_stack": provider_stack,
            "hf_home": os.environ.get("HF_HOME"),
            "hf_hub_offline": os.environ.get("HF_HUB_OFFLINE"),
        },
        "model_load_ms": load_ms,
        "model_files": _model_file_metadata(),
        "summary": {
            "overall": summarize_samples(results),
            "by_suite": by_suite,
            "by_role": by_role,
        },
        "samples": results,
    }


def _paired_wins(baseline: list[dict[str, Any]], candidate: list[dict[str, Any]]) -> dict[str, int]:
    baseline_by_id = {sample["id"]: sample for sample in baseline}
    candidate_by_id = {sample["id"]: sample for sample in candidate}
    wins = losses = ties = 0
    for sample_id in baseline_by_id.keys() & candidate_by_id.keys():
        first = baseline_by_id[sample_id]
        second = candidate_by_id[sample_id]
        if not first.get("counts") or not second.get("counts"):
            continue
        reference_characters = first["counts"]["reference_characters"]
        if reference_characters <= 0:
            continue
        baseline_cer = first["counts"]["distance"] / reference_characters
        candidate_cer = second["counts"]["distance"] / reference_characters
        if candidate_cer < baseline_cer:
            wins += 1
        elif candidate_cer > baseline_cer:
            losses += 1
        else:
            ties += 1
    return {"candidate_wins": wins, "candidate_losses": losses, "ties": ties}


def _statistical_outcome(paired: dict[str, Any]) -> str:
    delta = paired["delta"]
    lower, upper = paired["ci95"]
    if delta is None or lower is None or upper is None:
        return "inconclusive"
    if upper < 0:
        return "candidate_better"
    if lower > 0:
        return "candidate_worse"
    if delta == 0 and lower == 0 and upper == 0:
        return "tied"
    return "inconclusive"


_WORKLOAD_CONFIGURATION_FIELDS = (
    "pipeline",
    "join",
    "confidence_threshold",
    "repeats",
    "warmups",
    "seed",
    "suite_filter",
    "role_filter",
    "include_unscored",
)


def _comparison_workload(result: dict[str, Any], label: str) -> dict[str, Any]:
    configuration = result.get("configuration")
    if not isinstance(configuration, dict):
        raise BenchmarkError(f"{label} report has no benchmark configuration")

    missing = [field for field in _WORKLOAD_CONFIGURATION_FIELDS if field not in configuration]
    if missing:
        raise BenchmarkError(f"{label} report is missing workload configuration: {', '.join(missing)}")

    # Preserve unknown fields so a future workload option cannot be silently
    # ignored by an older comparison contract.
    workload = dict(configuration)
    for field in ("suite_filter", "role_filter"):
        values = workload[field]
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise BenchmarkError(f"{label} report has an invalid {field}")
        workload[field] = sorted(values)
    return workload


def _selected_sample_ids(result: dict[str, Any], label: str) -> list[str]:
    samples = result.get("samples")
    if not isinstance(samples, list):
        raise BenchmarkError(f"{label} report has no sample results")

    sample_ids = []
    for index, sample in enumerate(samples):
        sample_id = sample.get("id") if isinstance(sample, dict) else None
        if not isinstance(sample_id, str) or not sample_id:
            raise BenchmarkError(f"{label} report sample {index} has no valid ID")
        sample_ids.append(sample_id)

    duplicates = sorted(sample_id for sample_id, count in Counter(sample_ids).items() if count > 1)
    if duplicates:
        raise BenchmarkError(f"{label} report contains duplicate sample IDs: {', '.join(duplicates)}")
    return sample_ids


def _local_corpus_files(result: dict[str, Any], label: str, sample_ids: list[str]) -> dict[str, Any]:
    local_files = result.get("corpus", {}).get("local_files")
    if not isinstance(local_files, dict):
        raise BenchmarkError(f"{label} report has no local corpus file metadata")

    expected_ids = set(sample_ids)
    actual_ids = set(local_files)
    if actual_ids != expected_ids:
        missing = sorted(expected_ids - actual_ids)
        extra = sorted(actual_ids - expected_ids)
        details = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if extra:
            details.append(f"unexpected: {', '.join(extra)}")
        raise BenchmarkError(f"{label} report local corpus files do not match its samples ({'; '.join(details)})")

    for sample_id in sample_ids:
        metadata = local_files[sample_id]
        if not isinstance(metadata, dict) or not isinstance(metadata.get("sha256"), str) or not metadata["sha256"]:
            raise BenchmarkError(f"{label} report has invalid local corpus metadata for {sample_id}")
    return local_files


def compare_results(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    bootstrap_iterations: int = 10_000,
    bootstrap_seed: int = 1729,
    min_real_samples: int = 100,
    min_games: int = 5,
    max_p95_ms: float = 500.0,
    max_latency_regression: float = 0.25,
) -> dict[str, Any]:
    for label, result in (("Baseline", baseline), ("Candidate", candidate)):
        if result.get("schema_version") != 1:
            raise BenchmarkError(f"{label} report does not use schema version 1")

    baseline_manifest = baseline.get("corpus", {}).get("manifest_sha256")
    candidate_manifest = candidate.get("corpus", {}).get("manifest_sha256")
    if not isinstance(baseline_manifest, str) or not baseline_manifest:
        raise BenchmarkError("Baseline report has no corpus manifest hash")
    if not isinstance(candidate_manifest, str) or not candidate_manifest:
        raise BenchmarkError("Candidate report has no corpus manifest hash")
    if baseline_manifest != candidate_manifest:
        raise BenchmarkError("Cannot compare runs made from different corpus manifests")

    baseline_ocr_source = baseline.get("application", {}).get("ocr_source_sha256")
    candidate_ocr_source = candidate.get("application", {}).get("ocr_source_sha256")
    if not isinstance(baseline_ocr_source, str) or not baseline_ocr_source:
        raise BenchmarkError("Baseline report has no Interpreter OCR source hash")
    if not isinstance(candidate_ocr_source, str) or not candidate_ocr_source:
        raise BenchmarkError("Candidate report has no Interpreter OCR source hash")
    if baseline_ocr_source != candidate_ocr_source:
        raise BenchmarkError("Cannot compare runs made with different Interpreter OCR pipeline source")

    baseline_workload = _comparison_workload(baseline, "Baseline")
    candidate_workload = _comparison_workload(candidate, "Candidate")
    if baseline_workload != candidate_workload:
        fields = baseline_workload.keys() | candidate_workload.keys()
        changed = sorted(
            field
            for field in fields
            if field not in baseline_workload
            or field not in candidate_workload
            or baseline_workload[field] != candidate_workload[field]
        )
        raise BenchmarkError(f"Cannot compare runs made with different workload configuration: {', '.join(changed)}")

    baseline_ids = _selected_sample_ids(baseline, "Baseline")
    candidate_ids = _selected_sample_ids(candidate, "Candidate")
    if baseline_ids != candidate_ids:
        baseline_set = set(baseline_ids)
        candidate_set = set(candidate_ids)
        missing = sorted(baseline_set - candidate_set)
        extra = sorted(candidate_set - baseline_set)
        details = []
        if missing:
            details.append(f"missing from candidate: {', '.join(missing)}")
        if extra:
            details.append(f"candidate-only: {', '.join(extra)}")
        if not details:
            details.append("sample order differs")
        raise BenchmarkError(f"Cannot compare runs with different selected sample IDs ({'; '.join(details)})")

    baseline_files = _local_corpus_files(baseline, "Baseline", baseline_ids)
    candidate_files = _local_corpus_files(candidate, "Candidate", candidate_ids)
    if baseline_files != candidate_files:
        changed = [sample_id for sample_id in baseline_ids if baseline_files[sample_id] != candidate_files[sample_id]]
        raise BenchmarkError(f"Cannot compare runs made from different local corpus files: {', '.join(changed)}")

    paired = bootstrap_cer_delta(
        baseline["samples"],
        candidate["samples"],
        iterations=bootstrap_iterations,
        seed=bootstrap_seed,
    )
    outcome = _statistical_outcome(paired)
    baseline_summary = summarize_samples(baseline["samples"])
    candidate_summary = summarize_samples(candidate["samples"])
    wins = _paired_wins(baseline["samples"], candidate["samples"])

    baseline_p95 = baseline_summary["latency_ms"]["p95"]
    candidate_p95 = candidate_summary["latency_ms"]["p95"]
    latency_ratio = candidate_p95 / baseline_p95 if baseline_p95 and candidate_p95 is not None else None

    candidate_samples = {sample["id"]: sample for sample in candidate["samples"]}
    real_verified = [
        sample
        for sample in baseline["samples"]
        if sample["role"] in {"evaluation", "holdout"}
        and sample["annotation_status"] == "verified"
        and sample["id"] in candidate_samples
        and sample.get("counts")
        and candidate_samples[sample["id"]].get("counts")
    ]
    games = {sample.get("game") for sample in real_verified if sample.get("game")}

    blockers = []
    if outcome != "candidate_better":
        blockers.append(f"paired CER outcome is {outcome}, not candidate_better")
    if len(real_verified) < min_real_samples:
        blockers.append(
            f"only {len(real_verified)} verified real evaluation samples; require at least {min_real_samples}"
        )
    if len(games) < min_games:
        blockers.append(f"only {len(games)} represented games; require at least {min_games}")
    baseline_exact = baseline_summary["exact_match_rate"]
    candidate_exact = candidate_summary["exact_match_rate"]
    if baseline_exact is not None and candidate_exact is not None and candidate_exact < baseline_exact:
        blockers.append("candidate exact-match rate regressed")
    if candidate_p95 is None or candidate_p95 > max_p95_ms:
        blockers.append(f"candidate p95 latency must be at most {max_p95_ms:.0f} ms")
    if latency_ratio is None or latency_ratio > 1 + max_latency_regression:
        blockers.append(f"candidate p95 latency regression exceeds {max_latency_regression:.0%}")
    if candidate_summary["errors"]:
        blockers.append(f"candidate had {candidate_summary['errors']} sample errors")

    suites = sorted(
        {suite for sample in baseline["samples"] for suite in sample["suites"]}
        & {suite for sample in candidate["samples"] for suite in sample["suites"]}
    )
    by_suite = {}
    for suite in suites:
        baseline_suite = [sample for sample in baseline["samples"] if suite in sample["suites"]]
        candidate_suite = [sample for sample in candidate["samples"] if suite in sample["suites"]]
        suite_paired = bootstrap_cer_delta(
            baseline_suite,
            candidate_suite,
            iterations=bootstrap_iterations,
            seed=bootstrap_seed,
        )
        by_suite[suite] = {
            "baseline": summarize_samples(baseline_suite),
            "candidate": summarize_samples(candidate_suite),
            "paired_cer": suite_paired,
            "outcome": _statistical_outcome(suite_paired),
            **_paired_wins(baseline_suite, candidate_suite),
        }

    return {
        "schema_version": 1,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "baseline": baseline.get("label"),
        "candidate": candidate.get("label"),
        "baseline_summary": baseline_summary,
        "candidate_summary": candidate_summary,
        "paired_cer": paired,
        "statistical_outcome": outcome,
        **wins,
        "latency_p95_ratio": latency_ratio,
        "promotion_gate": {
            "ready": not blockers,
            "blockers": blockers,
            "verified_real_samples": len(real_verified),
            "represented_games": len(games),
            "requirements": {
                "min_real_samples": min_real_samples,
                "min_games": min_games,
                "max_p95_ms": max_p95_ms,
                "max_latency_regression": max_latency_regression,
            },
        },
        "by_suite": by_suite,
    }


def format_summary(summary: dict[str, Any]) -> str:
    def percentage(value: float | None) -> str:
        return "n/a" if value is None else f"{value:.2%}"

    latency = summary["latency_ms"]
    return (
        f"CER={percentage(summary['micro_cer'])}, exact={percentage(summary['exact_match_rate'])}, "
        f"median={latency['median']:.1f} ms, p95={latency['p95']:.1f} ms, "
        f"scored={summary['samples_scored']}, errors={summary['errors']}"
    )
