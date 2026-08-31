"""Standard-library utilities for the Interpreter translation benchmark."""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
import statistics
import unicodedata
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
DEFAULT_SOURCES = HERE / "sources.json"
DEFAULT_MODELS = HERE / "models.json"
DEFAULT_REVIEWS = HERE / "reviews.json"
DEFAULT_DATA_DIR = HERE / "data"
DEFAULT_RESULTS_DIR = HERE / "results"
DEFAULT_LOCK = DEFAULT_DATA_DIR / "corpus.lock.json"

TRACKS = {"screen", "normalized"}
TEXT_TYPES = {"dialogue", "menu", "system"}
LENGTH_BUCKETS = {"short", "medium", "long"}
REFERENCE_STATUSES = {
    "single_source_review",
    "source_review_with_alternate",
    "independently_verified",
}

# Script characters, intentionally excluding punctuation such as the katakana
# middle dot (U+30FB). Punctuation-only output is not untranslated Japanese.
_JAPANESE_RE = re.compile(r"[\u3041-\u3096\u309d-\u309f\u30a1-\u30fa\u30fd-\u30ff\u3400-\u9fff\uff66-\uff9d]")
_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9])\d+(?:[.,]\d+)*(?![A-Za-z0-9])")
_WHITESPACE_RE = re.compile(r"\s+")


class BenchmarkError(RuntimeError):
    """A user-actionable benchmark failure."""


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BenchmarkError(f"File not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise BenchmarkError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BenchmarkError(f"Expected a JSON object in {path}")
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


def fingerprint(value: Any) -> str:
    return sha256_bytes(canonical_json(value))


def collapse_whitespace(text: str | None) -> str:
    return _WHITESPACE_RE.sub(" ", (text or "").replace("\\", " ")).strip()


def comparison_text(text: str | None) -> str:
    return collapse_whitespace(unicodedata.normalize("NFKC", text or "")).casefold()


def has_japanese(text: str | None) -> bool:
    return bool(_JAPANESE_RE.search(text or ""))


def japanese_character_count(text: str | None) -> int:
    return len(_JAPANESE_RE.findall(text or ""))


def source_character_count(text: str) -> int:
    return sum(not character.isspace() for character in text)


def length_bucket(text: str, limits: dict[str, list[int]]) -> str:
    length = source_character_count(text)
    for name in ("short", "medium", "long"):
        lower, upper = limits[name]
        if lower <= length <= upper:
            return name
    raise BenchmarkError(f"Source length {length} is outside the configured buckets")


def stable_rank(seed: str, value: str) -> str:
    return sha256_bytes(f"{seed}\0{value}".encode())


def validate_source_registry(registry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if registry.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if not isinstance(registry.get("corpus_id"), str) or not registry["corpus_id"]:
        errors.append("corpus_id must be a non-empty string")
    if not isinstance(registry.get("sampling_seed"), str) or not registry["sampling_seed"]:
        errors.append("sampling_seed must be a non-empty string")
    maximum = registry.get("maximum_source_characters")
    if not isinstance(maximum, int) or maximum < 1:
        errors.append("maximum_source_characters must be a positive integer")

    buckets = registry.get("length_buckets")
    if not isinstance(buckets, dict) or set(buckets) != LENGTH_BUCKETS:
        errors.append(f"length_buckets must define exactly {sorted(LENGTH_BUCKETS)}")
    else:
        expected_lower = 1
        for name in ("short", "medium", "long"):
            bounds = buckets[name]
            if (
                not isinstance(bounds, list)
                or len(bounds) != 2
                or not all(isinstance(value, int) for value in bounds)
                or bounds[0] != expected_lower
                or bounds[1] < bounds[0]
            ):
                errors.append(f"length_buckets.{name} must be contiguous integer bounds")
                break
            expected_lower = bounds[1] + 1
        if isinstance(maximum, int) and buckets.get("long", [None, None])[1] != maximum:
            errors.append("long bucket upper bound must equal maximum_source_characters")

    sources = registry.get("sources")
    if not isinstance(sources, list) or not sources:
        return [*errors, "sources must be a non-empty list"]

    source_ids: set[str] = set()
    for index, source in enumerate(sources):
        prefix = f"sources[{index}]"
        if not isinstance(source, dict):
            errors.append(f"{prefix} must be an object")
            continue
        source_id = source.get("id")
        if not isinstance(source_id, str) or not source_id:
            errors.append(f"{prefix}.id must be a non-empty string")
        elif source_id in source_ids:
            errors.append(f"duplicate source id: {source_id}")
        else:
            source_ids.add(source_id)
        for field in ("game", "platform", "genre", "parser", "repository", "commit", "provenance_url", "license"):
            if not isinstance(source.get(field), str) or not source[field]:
                errors.append(f"{prefix}.{field} must be a non-empty string")
        if source.get("reference_status") not in REFERENCE_STATUSES:
            errors.append(f"{prefix}.reference_status must be one of {sorted(REFERENCE_STATUSES)}")
        if not isinstance(source.get("release_year"), int):
            errors.append(f"{prefix}.release_year must be an integer")
        if not str(source.get("repository", "")).startswith("https://github.com/"):
            errors.append(f"{prefix}.repository must be an HTTPS GitHub URL")
        if not re.fullmatch(r"[0-9a-f]{40}", str(source.get("commit", ""))):
            errors.append(f"{prefix}.commit must be a full lowercase Git commit")

        files = source.get("files")
        required_role = "archive" if source.get("parser") == "ds6_pc98" else "messages"
        if not isinstance(files, dict) or required_role not in files:
            errors.append(f"{prefix}.files must contain {required_role}")
        else:
            for role, metadata in files.items():
                file_prefix = f"{prefix}.files.{role}"
                if not isinstance(metadata, dict):
                    errors.append(f"{file_prefix} must be an object")
                    continue
                url = str(metadata.get("url", ""))
                raw_url = url.startswith("https://raw.githubusercontent.com/")
                archive_url = url == (
                    f"https://codeload.github.com/{str(source.get('repository', '')).removeprefix('https://github.com/')}/"
                    f"zip/{source.get('commit')}"
                )
                if not raw_url and not archive_url:
                    errors.append(
                        f"{file_prefix}.url must be a raw GitHub file or the source's exact-commit codeload ZIP"
                    )
                if not isinstance(metadata.get("path"), str) or not metadata["path"]:
                    errors.append(f"{file_prefix}.path must be a non-empty string")
                digest = metadata.get("sha256")
                if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                    errors.append(f"{file_prefix}.sha256 must be a lowercase SHA-256")

        quotas = source.get("quotas")
        if not isinstance(quotas, dict) or not quotas:
            errors.append(f"{prefix}.quotas must be a non-empty object")
        else:
            for text_type, by_length in quotas.items():
                if text_type not in TEXT_TYPES:
                    errors.append(f"{prefix}.quotas has unknown text type {text_type}")
                if not isinstance(by_length, dict) or set(by_length) != LENGTH_BUCKETS:
                    errors.append(f"{prefix}.quotas.{text_type} must define exactly {sorted(LENGTH_BUCKETS)}")
                elif not all(isinstance(value, int) and value >= 0 for value in by_length.values()):
                    errors.append(f"{prefix}.quotas.{text_type} values must be non-negative integers")
    return errors


def validate_model_registry(registry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if registry.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    models = registry.get("models")
    if not isinstance(models, dict) or not models:
        return [*errors, "models must be a non-empty object"]
    for model_id, model in models.items():
        prefix = f"models.{model_id}"
        if not isinstance(model, dict):
            errors.append(f"{prefix} must be an object")
            continue
        for field in ("label", "adapter", "repo_id", "license", "deployment_status"):
            if not isinstance(model.get(field), str) or not model[field]:
                errors.append(f"{prefix}.{field} must be a non-empty string")
        revision = model.get("revision")
        if revision is not None and not re.fullmatch(r"[0-9a-f]{40}", str(revision)):
            errors.append(f"{prefix}.revision must be null or a full lowercase commit")
        packages = model.get("packages")
        if not isinstance(packages, list) or not all(isinstance(item, str) and item for item in packages):
            errors.append(f"{prefix}.packages must be a string list")
        indexes = model.get("uv_indexes", [])
        if not isinstance(indexes, list) or not all(
            isinstance(item, str) and item.startswith("https://") for item in indexes
        ):
            errors.append(f"{prefix}.uv_indexes must be an HTTPS URL list when provided")
        if not isinstance(model.get("generation"), dict):
            errors.append(f"{prefix}.generation must be an object")
    return errors


def validate_reviews(reviews: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if reviews.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    entries = reviews.get("reviews")
    if not isinstance(entries, dict):
        return [*errors, "reviews must be an object keyed by pair ID"]
    for pair_id, review in entries.items():
        if not isinstance(pair_id, str) or not pair_id:
            errors.append("review pair IDs must be non-empty strings")
        if not isinstance(review, dict):
            errors.append(f"review {pair_id} must be an object")
            continue
        if review.get("status") not in {"verified", "rejected"}:
            errors.append(f"review {pair_id}.status must be verified or rejected")
        if review.get("reviewer_kind") != "human":
            errors.append(f"review {pair_id}.reviewer_kind must be human")
        if not isinstance(review.get("blind_to_model_outputs"), bool):
            errors.append(f"review {pair_id}.blind_to_model_outputs must be boolean")
    return errors


def apply_reviews(entries: list[dict[str, Any]], reviews: dict[str, Any]) -> list[dict[str, Any]]:
    by_id = reviews.get("reviews", {})
    known_ids = {entry["pair_id"] for entry in entries}
    unknown = sorted(set(by_id) - known_ids)
    if unknown:
        raise BenchmarkError(f"reviews.json refers to unknown pair IDs: {', '.join(unknown)}")

    output = []
    for entry in entries:
        review = by_id.get(entry["pair_id"])
        if review and review["status"] == "rejected":
            continue
        item = dict(entry)
        item["independently_verified"] = bool(
            review
            and review["status"] == "verified"
            and review["reviewer_kind"] == "human"
            and review["blind_to_model_outputs"]
        )
        if item["independently_verified"]:
            item["reference_status"] = "independently_verified"
        output.append(item)
    return output


def select_entries(entries: list[dict[str, Any]], registry: dict[str, Any]) -> list[dict[str, Any]]:
    """Select a frozen, stratified corpus without consulting model output."""

    seed = registry["sampling_seed"]
    sources = {source["id"]: source for source in registry["sources"]}
    by_stratum: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    pair_ids: set[str] = set()
    for entry in entries:
        pair_id = entry.get("pair_id")
        if not isinstance(pair_id, str) or not pair_id:
            raise BenchmarkError("Parsed entry has no pair_id")
        if pair_id in pair_ids:
            raise BenchmarkError(f"Parser produced duplicate pair ID: {pair_id}")
        pair_ids.add(pair_id)
        source_id = entry.get("source_id")
        if source_id not in sources:
            raise BenchmarkError(f"Parsed entry has unknown source ID: {source_id}")
        text_type = entry.get("text_type")
        bucket = entry.get("length_bucket")
        if text_type not in TEXT_TYPES or bucket not in LENGTH_BUCKETS:
            raise BenchmarkError(f"Parsed entry {pair_id} has invalid strata")
        by_stratum.setdefault((source_id, text_type, bucket), []).append(entry)

    selected: list[dict[str, Any]] = []
    for source in registry["sources"]:
        source_id = source["id"]
        for text_type, quotas in source["quotas"].items():
            for bucket in ("short", "medium", "long"):
                quota = quotas[bucket]
                if not quota:
                    continue
                available = by_stratum.get((source_id, text_type, bucket), [])
                if len(available) < quota:
                    raise BenchmarkError(
                        f"Corpus stratum {source_id}/{text_type}/{bucket} has {len(available)} entries; "
                        f"the frozen quota requires {quota}"
                    )
                ranked = sorted(available, key=lambda item: (stable_rank(seed, item["pair_id"]), item["pair_id"]))
                selected.extend(ranked[:quota])
    return sorted(selected, key=lambda item: item["pair_id"])


def expand_tracks(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for entry in entries:
        common = {
            key: entry[key]
            for key in (
                "pair_id",
                "source_id",
                "source_index",
                "game",
                "platform",
                "release_year",
                "genre",
                "text_type",
                "length_bucket",
                "references",
                "reference_status",
                "independently_verified",
                "provenance",
            )
        }
        screen = {**common, "id": f"{entry['pair_id']}::screen", "track": "screen", "source": entry["screen"]}
        samples.append(screen)
        normalized = entry.get("normalized")
        if normalized and comparison_text(normalized) != comparison_text(entry["screen"]):
            samples.append(
                {
                    **common,
                    "id": f"{entry['pair_id']}::normalized",
                    "track": "normalized",
                    "source": normalized,
                }
            )
    return sorted(samples, key=lambda item: item["id"])


def select_samples(
    lock: dict[str, Any],
    tracks: Iterable[str] | None = None,
    games: Iterable[str] | None = None,
    text_types: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    track_filter = set(tracks or [])
    game_filter = set(games or [])
    type_filter = set(text_types or [])
    unknown_tracks = track_filter - TRACKS
    if unknown_tracks:
        raise BenchmarkError(f"Unknown track(s): {', '.join(sorted(unknown_tracks))}")
    selected = []
    for sample in lock.get("samples", []):
        if track_filter and sample["track"] not in track_filter:
            continue
        if game_filter and sample["game"] not in game_filter:
            continue
        if type_filter and sample["text_type"] not in type_filter:
            continue
        selected.append(sample)
    return selected


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


def latency_summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    values = [value for sample in samples for value in sample.get("latencies_ms", [])]
    return {
        "measurements": len(values),
        "median": statistics.median(values) if values else None,
        "p95": percentile(values, 0.95),
        "mean": statistics.fmean(values) if values else None,
    }


def number_tokens(text: str | None) -> Counter[str]:
    normalized = unicodedata.normalize("NFKC", text or "")
    return Counter(_NUMBER_RE.findall(normalized))


def number_preservation(source: str, prediction: str) -> tuple[int, int]:
    expected = number_tokens(source)
    observed = number_tokens(prediction)
    total = sum(expected.values())
    preserved = sum(min(count, observed[token]) for token, count in expected.items())
    return preserved, total


def bootstrap_mean_delta(
    baseline: dict[str, float],
    candidate: dict[str, float],
    iterations: int = 10_000,
    seed: int = 1729,
) -> dict[str, Any]:
    ids = sorted(baseline.keys() & candidate.keys())
    if not ids:
        return {"pairs": 0, "delta": None, "ci95": [None, None], "iterations": 0, "seed": seed}
    differences = [candidate[sample_id] - baseline[sample_id] for sample_id in ids]
    observed = statistics.fmean(differences)
    rng = random.Random(seed)
    deltas = []
    for _ in range(iterations):
        deltas.append(statistics.fmean(differences[rng.randrange(len(differences))] for _ in differences))
    return {
        "pairs": len(ids),
        "delta": observed,
        "ci95": [percentile(deltas, 0.025), percentile(deltas, 0.975)],
        "iterations": iterations,
        "seed": seed,
    }


def modal_prediction(predictions: list[str]) -> str:
    if not predictions:
        return ""
    counts = Counter(predictions)
    maximum = max(counts.values())
    return next(prediction for prediction in predictions if counts[prediction] == maximum)
