"""Shared utilities for the Interpreter OCR benchmark.

This module intentionally uses only the Python standard library so comparison
reports can be generated outside either model environment.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
import unicodedata
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
DEFAULT_MANIFEST = HERE / "corpus.json"
DEFAULT_DATA_DIR = HERE / "data"
DEFAULT_RESULTS_DIR = HERE / "results"

SCOREABLE_STATUSES = {"verified", "single_review"}
KNOWN_STATUSES = SCOREABLE_STATUSES | {"draft", "unscored"}
KNOWN_ROLES = {"smoke", "evaluation", "holdout", "diagnostic", "stress"}


class BenchmarkError(RuntimeError):
    """A user-actionable benchmark error."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BenchmarkError(f"File not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise BenchmarkError(f"Invalid JSON in {path}: {exc}") from exc


def _load_sample_pack(manifest_path: Path, relative_path: str) -> list[dict[str, Any]]:
    pack_path = (manifest_path.parent / relative_path).resolve()
    manifest_directory = manifest_path.parent.resolve()
    if manifest_directory not in pack_path.parents:
        raise BenchmarkError(f"Sample pack must stay under {manifest_directory}: {relative_path}")

    pack = _read_json(pack_path)
    if not isinstance(pack, dict) or pack.get("schema_version") != 1:
        raise BenchmarkError(f"Sample pack must be a schema-version-1 object: {pack_path}")
    defaults = pack.get("defaults", {})
    samples = pack.get("samples")
    if not isinstance(defaults, dict) or not isinstance(samples, list):
        raise BenchmarkError(f"Sample pack defaults/samples are malformed: {pack_path}")

    expanded = []
    for index, sample in enumerate(samples):
        if not isinstance(sample, dict):
            raise BenchmarkError(f"Sample pack entry {index} must be an object: {pack_path}")
        merged = {**defaults, **sample}
        for field in ("source", "image", "annotation"):
            merged[field] = {**defaults.get(field, {}), **sample.get(field, {})}
        default_notes = defaults.get("annotation", {}).get("notes")
        sample_notes = sample.get("annotation", {}).get("notes")
        if default_notes and sample_notes:
            merged["annotation"]["notes"] = f"{default_notes} {sample_notes}"
        for field in ("suites", "tags"):
            merged[field] = list(dict.fromkeys([*defaults.get(field, []), *sample.get(field, [])]))
        expanded.append(merged)
    return expanded


def load_json(path: Path) -> dict[str, Any]:
    value = _read_json(path)
    if not isinstance(value, dict):
        raise BenchmarkError(f"Expected a JSON object in {path}")

    sample_files = value.get("sample_files", [])
    if not isinstance(sample_files, list) or not all(isinstance(item, str) and item for item in sample_files):
        raise BenchmarkError(f"sample_files must be a string list in {path}")
    if sample_files:
        direct_samples = value.get("samples", [])
        if not isinstance(direct_samples, list):
            raise BenchmarkError(f"samples must be a list in {path}")
        value["samples"] = [
            *direct_samples,
            *(sample for item in sample_files for sample in _load_sample_pack(path, item)),
        ]
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_fingerprint(manifest: dict[str, Any]) -> str:
    return sha256_bytes(canonical_json(manifest))


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if manifest.get("schema_version") != 1:
        errors.append("schema_version must be 1")

    samples = manifest.get("samples")
    if not isinstance(samples, list) or not samples:
        return [*errors, "samples must be a non-empty list"]

    ids: set[str] = set()
    paths: set[str] = set()
    for index, sample in enumerate(samples):
        prefix = f"samples[{index}]"
        sample_id = sample.get("id")
        if not isinstance(sample_id, str) or not sample_id:
            errors.append(f"{prefix}.id must be a non-empty string")
        elif sample_id in ids:
            errors.append(f"duplicate sample id: {sample_id}")
        else:
            ids.add(sample_id)

        relative = sample.get("path")
        if not isinstance(relative, str) or not relative:
            errors.append(f"{prefix}.path must be a non-empty string")
        else:
            path = Path(relative)
            if path.is_absolute() or ".." in path.parts:
                errors.append(f"{prefix}.path must stay under the data directory")
            elif relative in paths:
                errors.append(f"duplicate sample path: {relative}")
            else:
                paths.add(relative)

        suites = sample.get("suites")
        if not isinstance(suites, list) or not suites or not all(isinstance(x, str) and x for x in suites):
            errors.append(f"{prefix}.suites must be a non-empty string list")

        role = sample.get("role")
        if role not in KNOWN_ROLES:
            errors.append(f"{prefix}.role must be one of {sorted(KNOWN_ROLES)}")

        source = sample.get("source")
        if not isinstance(source, dict) or source.get("kind") not in {"url", "git"}:
            errors.append(f"{prefix}.source.kind must be url or git")
        elif source["kind"] == "url":
            if not str(source.get("url", "")).startswith("https://"):
                errors.append(f"{prefix}.source.url must use https")
            if not source.get("page_url"):
                errors.append(f"{prefix}.source.page_url is required for provenance")
            if not source.get("license"):
                errors.append(f"{prefix}.source.license is required")
        elif source["kind"] == "git":
            for field in ("ref", "git_path", "repository"):
                if not source.get(field):
                    errors.append(f"{prefix}.source.{field} is required")
        annotation = sample.get("annotation")
        if not isinstance(annotation, dict):
            errors.append(f"{prefix}.annotation must be an object")
        else:
            status = annotation.get("status")
            if status not in KNOWN_STATUSES:
                errors.append(f"{prefix}.annotation.status must be one of {sorted(KNOWN_STATUSES)}")
            if status in SCOREABLE_STATUSES and not isinstance(annotation.get("text"), str):
                errors.append(f"{prefix}.annotation.text is required for scoreable samples")

        image = sample.get("image", {})
        expected_hash = image.get("sha256")
        if expected_hash is not None and (
            not isinstance(expected_hash, str)
            or len(expected_hash) != 64
            or any(char not in "0123456789abcdef" for char in expected_hash)
        ):
            errors.append(f"{prefix}.image.sha256 must be a lowercase SHA-256 hex digest")

    return errors


def select_samples(
    manifest: dict[str, Any],
    suites: Iterable[str] | None = None,
    roles: Iterable[str] | None = None,
    include_unscored: bool = False,
) -> list[dict[str, Any]]:
    suite_filter = set(suites or [])
    role_filter = set(roles or [])
    selected = []
    for sample in manifest["samples"]:
        if suite_filter and not suite_filter.intersection(sample["suites"]):
            continue
        if role_filter and sample["role"] not in role_filter:
            continue
        status = sample["annotation"]["status"]
        if not include_unscored and status not in SCOREABLE_STATUSES:
            continue
        selected.append(sample)
    return selected


def normalize_text(text: str) -> str:
    """Normalize Japanese OCR text while retaining punctuation and content.

    NFKC makes full-width ASCII and compatibility characters comparable. All
    Unicode whitespace is removed because the app joins independently detected
    regions with spaces and the models do not promise line-break fidelity.
    """

    normalized = unicodedata.normalize("NFKC", text or "")
    return "".join(character for character in normalized if not character.isspace())


def edit_counts(reference: str, prediction: str) -> dict[str, int]:
    """Return Levenshtein substitutions, deletions, and insertions."""

    reference = normalize_text(reference)
    prediction = normalize_text(prediction)
    rows = len(reference) + 1
    columns = len(prediction) + 1
    costs = [[0] * columns for _ in range(rows)]
    operations = [[""] * columns for _ in range(rows)]

    for row in range(1, rows):
        costs[row][0] = row
        operations[row][0] = "deletion"
    for column in range(1, columns):
        costs[0][column] = column
        operations[0][column] = "insertion"

    operation_priority = {"match": 0, "substitution": 1, "deletion": 2, "insertion": 3}
    for row in range(1, rows):
        for column in range(1, columns):
            is_match = reference[row - 1] == prediction[column - 1]
            candidates = [
                (costs[row - 1][column - 1] + (0 if is_match else 1), "match" if is_match else "substitution"),
                (costs[row - 1][column] + 1, "deletion"),
                (costs[row][column - 1] + 1, "insertion"),
            ]
            cost, operation = min(candidates, key=lambda item: (item[0], operation_priority[item[1]]))
            costs[row][column] = cost
            operations[row][column] = operation

    counts = Counter({"substitutions": 0, "deletions": 0, "insertions": 0})
    row, column = len(reference), len(prediction)
    while row or column:
        operation = operations[row][column]
        if operation == "match":
            row -= 1
            column -= 1
        elif operation == "substitution":
            counts["substitutions"] += 1
            row -= 1
            column -= 1
        elif operation == "deletion":
            counts["deletions"] += 1
            row -= 1
        elif operation == "insertion":
            counts["insertions"] += 1
            column -= 1
        else:  # Only possible for the empty/empty cell.
            break

    distance = counts["substitutions"] + counts["deletions"] + counts["insertions"]
    return {
        "substitutions": counts["substitutions"],
        "deletions": counts["deletions"],
        "insertions": counts["insertions"],
        "distance": distance,
        "reference_characters": len(reference),
        "prediction_characters": len(prediction),
    }


def percentile(values: Iterable[float], quantile: float) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return float(ordered[lower] * (1 - weight) + ordered[upper] * weight)


def summarize_samples(samples: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [sample for sample in samples if sample.get("counts") and not sample.get("error")]
    positive = [sample for sample in scored if sample["counts"]["reference_characters"] > 0]
    negative = [sample for sample in scored if sample["counts"]["reference_characters"] == 0]
    latencies = [latency for sample in samples for latency in sample.get("latencies_ms", [])]

    total_reference = sum(sample["counts"]["reference_characters"] for sample in positive)
    total_distance = sum(sample["counts"]["distance"] for sample in positive)
    macro_cers = [sample["counts"]["distance"] / sample["counts"]["reference_characters"] for sample in positive]
    exact = sum(normalize_text(sample["reference"]) == normalize_text(sample["prediction"]) for sample in scored)
    false_positives = sum(bool(normalize_text(sample["prediction"])) for sample in negative)

    return {
        "samples_run": len(samples),
        "samples_scored": len(scored),
        "positive_samples": len(positive),
        "negative_samples": len(negative),
        "errors": sum(bool(sample.get("error")) for sample in samples),
        "micro_cer": total_distance / total_reference if total_reference else None,
        "macro_cer": statistics.fmean(macro_cers) if macro_cers else None,
        "exact_match_rate": exact / len(scored) if scored else None,
        "false_positive_rate": false_positives / len(negative) if negative else None,
        "substitutions": sum(sample["counts"]["substitutions"] for sample in positive),
        "deletions": sum(sample["counts"]["deletions"] for sample in positive),
        "insertions": sum(sample["counts"]["insertions"] for sample in positive),
        "reference_characters": total_reference,
        "latency_ms": {
            "measurements": len(latencies),
            "median": statistics.median(latencies) if latencies else None,
            "p95": percentile(latencies, 0.95),
            "mean": statistics.fmean(latencies) if latencies else None,
        },
        "nondeterministic_samples": sum(sample.get("unique_predictions", 0) > 1 for sample in samples),
    }


def bootstrap_cer_delta(
    baseline_samples: list[dict[str, Any]],
    candidate_samples: list[dict[str, Any]],
    iterations: int = 10_000,
    seed: int = 1729,
) -> dict[str, Any]:
    baseline_by_id = {sample["id"]: sample for sample in baseline_samples}
    candidate_by_id = {sample["id"]: sample for sample in candidate_samples}
    common = []
    for sample_id in sorted(baseline_by_id.keys() & candidate_by_id.keys()):
        baseline = baseline_by_id[sample_id]
        candidate = candidate_by_id[sample_id]
        if baseline.get("error") or candidate.get("error") or not baseline.get("counts") or not candidate.get("counts"):
            continue
        if baseline["counts"]["reference_characters"] <= 0:
            continue
        if normalize_text(baseline["reference"]) != normalize_text(candidate["reference"]):
            raise BenchmarkError(f"Reference changed between runs for sample {sample_id}")
        common.append((baseline, candidate))

    if not common:
        return {"samples": 0, "delta": None, "ci95": [None, None], "iterations": 0}

    def micro_cer(items: list[tuple[dict[str, Any], dict[str, Any]]], side: int) -> float:
        distance = sum(item[side]["counts"]["distance"] for item in items)
        characters = sum(item[side]["counts"]["reference_characters"] for item in items)
        return distance / characters

    observed = micro_cer(common, 1) - micro_cer(common, 0)
    rng = random.Random(seed)
    deltas = []
    for _ in range(iterations):
        resample = [common[rng.randrange(len(common))] for _ in range(len(common))]
        deltas.append(micro_cer(resample, 1) - micro_cer(resample, 0))

    return {
        "samples": len(common),
        "delta": observed,
        "ci95": [percentile(deltas, 0.025), percentile(deltas, 0.975)],
        "iterations": iterations,
        "seed": seed,
    }


def modal_prediction(predictions: list[str]) -> str:
    if not predictions:
        return ""
    counts = Counter(predictions)
    highest = max(counts.values())
    return next(prediction for prediction in predictions if counts[prediction] == highest)
