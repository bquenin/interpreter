"""Generate and score model-blind human translation review packets."""

from __future__ import annotations

import csv
import math
import time
from pathlib import Path
from typing import Any

from benchlib import BenchmarkError, fingerprint, stable_rank, write_json

IMMUTABLE_FIELDS = (
    "review_id",
    "sample_id",
    "game",
    "platform",
    "track",
    "text_type",
    "length_bucket",
    "source",
    "translation_a",
    "translation_b",
)
REVIEW_FIELDS = (*IMMUTABLE_FIELDS, "preference", "severity", "notes")
SPREADSHEET_FORMULA_PREFIXES = ("=", "+", "-", "@")


def _spreadsheet_safe_cell(value: Any) -> Any:
    """Encode a CSV cell as text without changing its canonical in-memory value."""
    if not isinstance(value, str) or not value:
        return value
    stripped = value.lstrip(" \t\r\n")
    if value.startswith(("'", "\t", "\r", "\n")) or stripped.startswith(SPREADSHEET_FORMULA_PREFIXES):
        return f"'{value}"
    return value


def _spreadsheet_safe_row(row: dict[str, Any]) -> dict[str, Any]:
    return {field: _spreadsheet_safe_cell(value) for field, value in row.items()}


def _paired_samples(baseline: dict[str, Any], candidate: dict[str, Any], track: str) -> list[tuple[Any, Any]]:
    first = {sample["id"]: sample for sample in baseline.get("samples", []) if sample["track"] == track}
    second = {sample["id"]: sample for sample in candidate.get("samples", []) if sample["track"] == track}
    if first.keys() != second.keys():
        raise BenchmarkError("Blind review inputs do not contain identical selected samples")
    for sample_id in first:
        identity = (first[sample_id]["source"], first[sample_id]["references"])
        if identity != (second[sample_id]["source"], second[sample_id]["references"]):
            raise BenchmarkError(f"Blind review source/reference mismatch for {sample_id}")
    return [(first[sample_id], second[sample_id]) for sample_id in sorted(first)]


def create_blind_packet(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    packet_path: Path,
    key_path: Path,
    track: str = "screen",
    limit: int | None = None,
    seed: int = 1729,
) -> dict[str, Any]:
    if baseline.get("model_id") == candidate.get("model_id"):
        raise BenchmarkError("Blind review requires two different model IDs")
    pairs = _paired_samples(baseline, candidate, track)
    if limit is not None:
        if limit < 1:
            raise BenchmarkError("Blind review limit must be at least 1")
        pairs = sorted(
            pairs,
            key=lambda pair: (stable_rank(f"blind-packet-{seed}", pair[0]["id"]), pair[0]["id"]),
        )[:limit]
        pairs.sort(key=lambda pair: pair[0]["id"])

    rows = []
    assignments = {}
    baseline_id = baseline["model_id"]
    candidate_id = candidate["model_id"]
    for index, (first, second) in enumerate(pairs, start=1):
        review_id = f"R{index:04d}"
        swap = int(stable_rank(f"blind-side-{seed}", first["id"])[-1], 16) % 2 == 1
        if swap:
            translation_a, translation_b = second["prediction"], first["prediction"]
            model_a, model_b = candidate_id, baseline_id
        else:
            translation_a, translation_b = first["prediction"], second["prediction"]
            model_a, model_b = baseline_id, candidate_id
        row = {
            "review_id": review_id,
            "sample_id": first["id"],
            "game": first["game"],
            "platform": first["platform"],
            "track": first["track"],
            "text_type": first["text_type"],
            "length_bucket": first["length_bucket"],
            "source": first["source"],
            "translation_a": translation_a,
            "translation_b": translation_b,
            "preference": "",
            "severity": "",
            "notes": "",
        }
        rows.append(row)
        assignments[review_id] = {"sample_id": first["id"], "model_a": model_a, "model_b": model_b}

    packet_path.parent.mkdir(parents=True, exist_ok=True)
    exported_rows = [_spreadsheet_safe_row(row) for row in rows]
    with packet_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        writer.writerows(exported_rows)
    immutable = [{field: row[field] for field in IMMUTABLE_FIELDS} for row in rows]
    exported_immutable = [{field: row[field] for field in IMMUTABLE_FIELDS} for row in exported_rows]
    key = {
        "schema_version": 2,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "models": [baseline_id, candidate_id],
        "baseline_model_id": baseline_id,
        "candidate_model_id": candidate_id,
        "track": track,
        "seed": seed,
        "packet_fingerprint": fingerprint(immutable),
        "export_fingerprint": fingerprint(exported_immutable),
        "assignments": assignments,
    }
    write_json(key_path, key)
    return {"rows": len(rows), "packet": str(packet_path), "key": str(key_path)}


def _wilson_interval(wins: int, total: int) -> list[float | None]:
    if not total:
        return [None, None]
    z = 1.959963984540054
    probability = wins / total
    denominator = 1 + z * z / total
    center = (probability + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(probability * (1 - probability) / total + z * z / (4 * total * total)) / denominator
    return [center - margin, center + margin]


def score_blind_packet(packet_path: Path, key: dict[str, Any]) -> dict[str, Any]:
    try:
        with packet_path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except FileNotFoundError as exc:
        raise BenchmarkError(f"Blind review packet not found: {packet_path}") from exc
    if not rows or tuple(rows[0]) != REVIEW_FIELDS:
        raise BenchmarkError("Blind review CSV columns changed or packet is empty")
    immutable = [{field: row[field] for field in IMMUTABLE_FIELDS} for row in rows]
    if fingerprint(immutable) != key.get("export_fingerprint"):
        raise BenchmarkError("Blind review packet source text or translations changed after randomization")
    assignments = key.get("assignments", {})
    if {row["review_id"] for row in rows} != set(assignments):
        raise BenchmarkError("Blind review packet rows do not match its separate key")

    baseline_id = key["baseline_model_id"]
    candidate_id = key["candidate_model_id"]
    counts = {baseline_id: 0, candidate_id: 0, "tie": 0, "invalid": 0}
    judgments = 0
    for row in rows:
        preference = row["preference"].strip().upper()
        if not preference:
            continue
        if preference not in {"A", "B", "TIE", "INVALID"}:
            raise BenchmarkError(
                f"{row['review_id']} preference must be A, B, TIE, INVALID, or blank; got {preference!r}"
            )
        judgments += 1
        if preference in {"A", "B"}:
            model_id = assignments[row["review_id"]][f"model_{preference.lower()}"]
            counts[model_id] += 1
        elif preference == "TIE":
            counts["tie"] += 1
        else:
            counts["invalid"] += 1

    candidate_wins = counts[candidate_id]
    baseline_wins = counts[baseline_id]
    decisive = candidate_wins + baseline_wins
    return {
        "schema_version": 1,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "models": [baseline_id, candidate_id],
        "packet_fingerprint": key["packet_fingerprint"],
        "judgments": judgments,
        "decisive_judgments": decisive,
        "candidate_wins": candidate_wins,
        "baseline_wins": baseline_wins,
        "ties": counts["tie"],
        "invalid": counts["invalid"],
        "candidate_win_rate": candidate_wins / decisive if decisive else None,
        "candidate_win_rate_ci95": _wilson_interval(candidate_wins, decisive),
    }


def create_reference_packet(
    lock: dict[str, Any],
    *,
    packet_path: Path,
    limit: int | None = None,
    seed: int = 1729,
) -> int:
    pairs = list(lock["pairs"])
    if limit is not None:
        if limit < 1:
            raise BenchmarkError("Reference review limit must be at least 1")
        pairs = sorted(
            pairs,
            key=lambda pair: (stable_rank(f"reference-packet-{seed}", pair["pair_id"]), pair["pair_id"]),
        )[:limit]
    fields = (
        "pair_id",
        "game",
        "platform",
        "text_type",
        "length_bucket",
        "screen_source",
        "normalized_source",
        "reference_1",
        "reference_2",
        "decision",
        "corrected_reference",
        "notes",
    )
    packet_path.parent.mkdir(parents=True, exist_ok=True)
    with packet_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for pair in sorted(pairs, key=lambda item: item["pair_id"]):
            writer.writerow(
                _spreadsheet_safe_row(
                    {
                        "pair_id": pair["pair_id"],
                        "game": pair["game"],
                        "platform": pair["platform"],
                        "text_type": pair["text_type"],
                        "length_bucket": pair["length_bucket"],
                        "screen_source": pair["screen"],
                        "normalized_source": pair.get("normalized") or "",
                        "reference_1": pair["references"][0],
                        "reference_2": pair["references"][1] if len(pair["references"]) > 1 else "",
                        "decision": "",
                        "corrected_reference": "",
                        "notes": "",
                    }
                )
            )
    return len(pairs)
