#!/usr/bin/env python3
"""CLI for the Interpreter Japanese-to-English translation benchmark."""

from __future__ import annotations

import argparse
import difflib
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from benchlib import (
    DEFAULT_DATA_DIR,
    DEFAULT_LOCK,
    DEFAULT_MODELS,
    DEFAULT_RESULTS_DIR,
    DEFAULT_REVIEWS,
    DEFAULT_SOURCES,
    REPO_ROOT,
    BenchmarkError,
    comparison_text,
    fingerprint,
    load_json,
    validate_model_registry,
    validate_reviews,
    validate_source_registry,
    write_json,
)
from corpus import inventory, load_and_validate_lock, prepare_corpus
from metrics import compare_results, format_scored_summary, score_results
from review import create_blind_packet, create_reference_packet, score_blind_packet
from runner import run_benchmark

DEFAULT_CANDIDATES = ["quickmt", "lfm2-350m", "hy-mt-1.8b", "riva-4b-v2"]


def _configure_console_utf8() -> None:
    """Keep Japanese corpus output readable on legacy Windows consoles."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")


def _path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _safe_slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-")[:80] or "model"


def _add_registry_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--sources", type=_path, default=DEFAULT_SOURCES, help="Source/corpus registry JSON")
    parser.add_argument("--reviews", type=_path, default=DEFAULT_REVIEWS, help="Independent reference reviews JSON")
    parser.add_argument("--models", type=_path, default=DEFAULT_MODELS, help="Pinned model registry JSON")
    parser.add_argument("--data-dir", type=_path, default=DEFAULT_DATA_DIR, help="Ignored downloaded corpus directory")
    parser.add_argument("--lock", type=_path, default=DEFAULT_LOCK, help="Generated frozen corpus lock")


def _add_workload_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--track", action="append", dest="tracks", choices=["screen", "normalized"])
    parser.add_argument("--game", action="append", dest="games", help="Exact game title; repeat to select several")
    parser.add_argument("--text-type", action="append", dest="text_types", choices=["dialogue", "menu", "system"])
    parser.add_argument("--repeats", type=int, default=3, help="Timed translations per sample (default: 3)")
    parser.add_argument("--warmups", type=int, default=2, help="Untimed warm-up calls (default: 2)")
    parser.add_argument("--seed", type=int, default=1729, help="Deterministic order/generation seed")
    parser.add_argument("--limit", type=int, help="Deterministic smoke-test limit; omit for the full corpus")
    parser.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    inventory_parser = subparsers.add_parser("inventory", help="Show frozen corpus composition")
    _add_registry_arguments(inventory_parser)

    prepare = subparsers.add_parser("prepare", help="Download, hash-check, parse, and freeze the URL corpus")
    _add_registry_arguments(prepare)

    validate = subparsers.add_parser("validate", help="Validate registries, frozen records, and downloaded bytes")
    _add_registry_arguments(validate)

    run = subparsers.add_parser("run", help="Run one pinned model without requiring metric packages")
    _add_registry_arguments(run)
    _add_workload_arguments(run)
    run.add_argument("--model-id", required=True)
    run.add_argument("--label")
    run.add_argument("--output", type=_path, required=True)

    score = subparsers.add_parser("score", help="Add SacreBLEU chrF++/BLEU and optional COMET scores")
    score.add_argument("results", nargs="+", type=_path)
    score.add_argument("--output-dir", type=_path)
    score.add_argument("--comet", action="store_true", help="Also run pinned WMT22 reference-based COMET")
    score.add_argument("--comet-batch-size", type=int, default=16)

    compare = subparsers.add_parser("compare", help="Fail-closed paired comparison of two result reports")
    compare.add_argument("baseline", type=_path)
    compare.add_argument("candidate", type=_path)
    compare.add_argument("--output", type=_path)
    compare.add_argument("--blind-review", type=_path, help="Scored model-blind human review JSON")
    compare.add_argument("--bootstrap-iterations", type=int, default=10_000)
    compare.add_argument("--bootstrap-seed", type=int, default=1729)
    compare.add_argument("--min-verified-pairs", type=int, default=100)
    compare.add_argument("--min-games", type=int, default=5)
    compare.add_argument("--min-blind-judgments", type=int, default=100)
    compare.add_argument("--max-p95-ms", type=float, default=750.0)
    compare.add_argument("--max-latency-ratio", type=float, default=10.0)
    compare.add_argument("--max-artifact-gib", type=float, default=5.0)
    compare.add_argument("--max-artifact-ratio", type=float, default=4.0)
    compare.add_argument("--max-game-regression", type=float, default=2.0)
    compare.add_argument("--private-holdout-passed", action="store_true")
    compare.add_argument("--license-approved", action="store_true")

    matrix = subparsers.add_parser(
        "matrix", help="Run production and accessible candidates in isolated, pinned environments"
    )
    _add_registry_arguments(matrix)
    _add_workload_arguments(matrix)
    matrix.add_argument("--candidate", action="append", dest="candidates", help="Model ID; repeat for several")
    matrix.add_argument("--results-dir", type=_path, default=DEFAULT_RESULTS_DIR)
    matrix.add_argument("--skip-comet", action="store_true", help="Skip the slower semantic COMET metric")
    matrix.add_argument("--comet-batch-size", type=int, default=16)
    matrix.add_argument("--bootstrap-iterations", type=int, default=10_000)

    blind = subparsers.add_parser("blind-packet", help="Randomize a separate-key A/B human review CSV")
    blind.add_argument("baseline", type=_path)
    blind.add_argument("candidate", type=_path)
    blind.add_argument("--packet", type=_path, required=True)
    blind.add_argument("--key", type=_path, required=True)
    blind.add_argument("--track", choices=["screen", "normalized"], default="screen")
    blind.add_argument("--limit", type=int)
    blind.add_argument("--seed", type=int, default=1729)

    blind_score = subparsers.add_parser("blind-score", help="Decode a completed A/B CSV using its held key")
    blind_score.add_argument("packet", type=_path)
    blind_score.add_argument("key", type=_path)
    blind_score.add_argument("--output", type=_path, required=True)

    reference = subparsers.add_parser(
        "reference-packet", help="Create a pre-output bilingual review sheet for corpus references"
    )
    _add_registry_arguments(reference)
    reference.add_argument("--packet", type=_path, required=True)
    reference.add_argument("--limit", type=int)
    reference.add_argument("--seed", type=int, default=1729)

    cache = subparsers.add_parser(
        "cache-audit", help="Find context-free corpus texts that can collide in production's fuzzy cache"
    )
    _add_registry_arguments(cache)
    cache.add_argument("--threshold", type=float, default=0.9)
    cache.add_argument("--output", type=_path)
    return parser


def _load_registries(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    sources = load_json(args.sources)
    reviews = load_json(args.reviews)
    models = load_json(args.models)
    errors = [
        *validate_source_registry(sources),
        *validate_reviews(reviews),
        *validate_model_registry(models),
    ]
    if errors:
        raise BenchmarkError("Benchmark registry validation failed:\n- " + "\n- ".join(errors))
    return sources, reviews, models


def _load_lock(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    sources, reviews, models = _load_registries(args)
    lock = load_and_validate_lock(args.lock, args.data_dir, sources, reviews)
    return lock, models, sources


def _print_inventory(value: dict[str, Any]) -> None:
    print(f"eligible pairs: {value['eligible_pairs']}")
    print(f"selected pairs: {value['selected_pairs']}")
    print(f"expanded samples: {value['samples']}")
    print(f"independently verified pairs: {value['verified_pairs']}")
    for field in ("games", "platforms", "text_types", "length_buckets", "tracks"):
        print(f"{field}:")
        for name, count in value[field].items():
            print(f"  {name}: {count}")


def _prepare(args: argparse.Namespace) -> dict[str, Any]:
    sources, reviews, _ = _load_registries(args)
    lock = prepare_corpus(sources, reviews, args.data_dir, args.sources, args.reviews)
    if args.lock.resolve() != (args.data_dir / "corpus.lock.json").resolve():
        write_json(args.lock, lock)
    print(f"corpus fingerprint: {fingerprint(lock)}")
    _print_inventory(inventory(lock))
    return lock


def _run(args: argparse.Namespace) -> dict[str, Any]:
    lock, models, _ = _load_lock(args)
    result = run_benchmark(
        lock=lock,
        lock_path=args.lock,
        model_registry=models,
        model_registry_path=args.models,
        model_id=args.model_id,
        repo_root=REPO_ROOT,
        label=args.label,
        tracks=args.tracks,
        games=args.games,
        text_types=args.text_types,
        repeats=args.repeats,
        warmups=args.warmups,
        seed=args.seed,
        limit=args.limit,
        device=args.device,
    )
    write_json(args.output, result)
    summary = result["summary"]["overall"]
    print(
        f"samples={summary['samples']} p95={summary['latency_ms']['p95']:.1f} ms "
        f"errors={summary['errors']} empty={summary['empty_predictions']}"
    )
    print(f"wrote {args.output}")
    return result


def _score(args: argparse.Namespace) -> list[Path]:
    values = score_results(
        [load_json(path) for path in args.results],
        include_comet=args.comet,
        comet_batch_size=args.comet_batch_size,
    )
    outputs = []
    for source, value in zip(args.results, values, strict=True):
        output_dir = args.output_dir or source.parent
        output = output_dir / f"{source.stem}-scored.json"
        write_json(output, value)
        outputs.append(output)
        print(f"{value['label']}: {format_scored_summary(value)}")
        print(f"wrote {output}")
    return outputs


def _comparison(args: argparse.Namespace) -> dict[str, Any]:
    comparison = compare_results(
        load_json(args.baseline),
        load_json(args.candidate),
        bootstrap_iterations=args.bootstrap_iterations,
        bootstrap_seed=args.bootstrap_seed,
        min_verified_pairs=args.min_verified_pairs,
        min_games=args.min_games,
        min_blind_judgments=args.min_blind_judgments,
        max_p95_ms=args.max_p95_ms,
        max_latency_ratio=args.max_latency_ratio,
        max_artifact_gib=args.max_artifact_gib,
        max_artifact_ratio=args.max_artifact_ratio,
        max_game_regression=args.max_game_regression,
        blind_review=load_json(args.blind_review) if args.blind_review else None,
        private_holdout_passed=args.private_holdout_passed,
        license_approved=args.license_approved,
    )
    output = args.output or args.candidate.with_name(f"comparison-{args.baseline.stem}-vs-{args.candidate.stem}.json")
    write_json(output, comparison)
    delta = comparison["paired_chrfpp"]["delta"]
    lower, upper = comparison["paired_chrfpp"]["ci95"]
    print(
        f"screen chrF++ delta: {delta:+.2f} (95% CI {lower:+.2f} to {upper:+.2f}); "
        f"outcome={comparison['statistical_outcome']}"
    )
    print(f"promotion gate: {'READY' if comparison['promotion_gate']['ready'] else 'NOT READY'}")
    for blocker in comparison["promotion_gate"]["blockers"]:
        print(f"  - {blocker}")
    print(f"wrote {output}")
    return comparison


def _workload_cli(args: argparse.Namespace) -> list[str]:
    output = [
        "--sources",
        str(args.sources),
        "--reviews",
        str(args.reviews),
        "--models",
        str(args.models),
        "--data-dir",
        str(args.data_dir),
        "--lock",
        str(args.lock),
        "--repeats",
        str(args.repeats),
        "--warmups",
        str(args.warmups),
        "--seed",
        str(args.seed),
        "--device",
        args.device,
    ]
    if args.limit is not None:
        output.extend(["--limit", str(args.limit)])
    for value in args.tracks or []:
        output.extend(["--track", value])
    for value in args.games or []:
        output.extend(["--game", value])
    for value in args.text_types or []:
        output.extend(["--text-type", value])
    return output


def _subprocess_environment(model_id: str) -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    environment["TOKENIZERS_PARALLELISM"] = "false"
    environment["HF_HOME"] = str(
        (Path(__file__).resolve().parent / ".cache" / "huggingface" / _safe_slug(model_id)).resolve()
    )
    environment.pop("HF_HUB_OFFLINE", None)
    return environment


def _uv_run(
    uv: str,
    packages: list[str],
    command: list[str],
    indexes: list[str] | None = None,
    index_strategy: str | None = None,
) -> list[str]:
    output = [uv, "run", "--isolated", "--no-project"]
    for index in indexes or []:
        output.extend(["--index", index])
    if index_strategy:
        output.extend(["--index-strategy", index_strategy])
    for package in packages:
        output.extend(["--with", package])
    return [*output, "python", *command]


def _matrix(args: argparse.Namespace) -> None:
    uv = shutil.which("uv")
    if not uv:
        raise BenchmarkError("uv is required for isolated candidate and metric environments")
    _prepare(args)
    _, model_registry, _ = _load_lock(args)
    candidates = args.candidates or DEFAULT_CANDIDATES
    unknown = sorted(set(candidates) - set(model_registry["models"]))
    if unknown:
        raise BenchmarkError(f"Unknown candidate model IDs: {', '.join(unknown)}")
    if "production" in candidates:
        raise BenchmarkError("production is always the matrix baseline; do not also list it as a candidate")

    timestamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    args.results_dir.mkdir(parents=True, exist_ok=True)
    script = str(Path(__file__).resolve())
    common = _workload_cli(args)
    baseline_path = args.results_dir / f"{timestamp}-production.json"
    print("running exact production baseline", flush=True)
    subprocess.run(
        [sys.executable, script, "run", "--model-id", "production", "--output", str(baseline_path), *common],
        check=True,
        cwd=REPO_ROOT,
        env=_subprocess_environment("production"),
    )

    successful = []
    failures = {}
    for model_id in candidates:
        model = model_registry["models"][model_id]
        path = args.results_dir / f"{timestamp}-{_safe_slug(model_id)}.json"
        print(f"running isolated candidate {model_id}", flush=True)
        command = _uv_run(
            uv,
            model["packages"],
            [script, "run", "--model-id", model_id, "--output", str(path), *common],
            model.get("uv_indexes"),
        )
        completed = subprocess.run(command, cwd=REPO_ROOT, env=_subprocess_environment(model_id), check=False)
        if completed.returncode:
            failures[model_id] = {"returncode": completed.returncode, "command": command}
            print(f"candidate {model_id} failed with exit code {completed.returncode}; continuing", flush=True)
        elif path.is_file():
            successful.append(path)
    if failures:
        write_json(args.results_dir / f"{timestamp}-failures.json", failures)
    if not successful:
        raise BenchmarkError("Every candidate failed; raw production result was preserved")

    metric_packages = ["sacrebleu==2.5.1"]
    metric_indexes = None
    score_command = [
        script,
        "score",
        str(baseline_path),
        *(str(path) for path in successful),
        "--output-dir",
        str(args.results_dir),
        "--comet-batch-size",
        str(args.comet_batch_size),
    ]
    if not args.skip_comet:
        metric_packages.extend(
            [
                "unbabel-comet==2.2.7",
                "torch==2.9.1",
                "transformers==4.57.6",
                "huggingface-hub==0.36.2",
                "pytorch-lightning==2.6.5",
                "torchmetrics==0.10.3",
                "sentencepiece==0.2.2",
                "numpy==1.26.4",
                "protobuf==4.25.9",
                "scipy==1.17.1",
                "hf-xet==1.6.0",
                "setuptools==80.9.0",
            ]
        )
        metric_indexes = ["https://download.pytorch.org/whl/cu128"]
        score_command.append("--comet")
    subprocess.run(
        _uv_run(
            uv,
            metric_packages,
            score_command,
            metric_indexes,
            "unsafe-best-match" if metric_indexes else None,
        ),
        check=True,
        cwd=REPO_ROOT,
        env=_subprocess_environment("metrics"),
    )

    scored_baseline = args.results_dir / f"{baseline_path.stem}-scored.json"
    for candidate_path in successful:
        scored_candidate = args.results_dir / f"{candidate_path.stem}-scored.json"
        comparison_path = args.results_dir / f"{timestamp}-comparison-production-vs-{candidate_path.stem}.json"
        subprocess.run(
            _uv_run(
                uv,
                ["sacrebleu==2.5.1"],
                [
                    script,
                    "compare",
                    str(scored_baseline),
                    str(scored_candidate),
                    "--output",
                    str(comparison_path),
                    "--bootstrap-iterations",
                    str(args.bootstrap_iterations),
                ],
            ),
            check=True,
            cwd=REPO_ROOT,
            env=_subprocess_environment("metrics"),
        )
    print(f"matrix results: {args.results_dir}")


def _cache_audit(lock: dict[str, Any], threshold: float) -> dict[str, Any]:
    if not 0 <= threshold <= 1:
        raise BenchmarkError("cache threshold must be between 0 and 1")
    samples = [sample for sample in lock["samples"] if sample["track"] == "screen"]
    collisions = []
    for index, first in enumerate(samples):
        for second in samples[index + 1 :]:
            ratio = difflib.SequenceMatcher(None, first["source"], second["source"]).ratio()
            if ratio < threshold:
                continue
            if {comparison_text(value) for value in first["references"]} == {
                comparison_text(value) for value in second["references"]
            }:
                continue
            collisions.append(
                {
                    "similarity": ratio,
                    "first": {key: first[key] for key in ("id", "game", "source", "references")},
                    "second": {key: second[key] for key in ("id", "game", "source", "references")},
                }
            )
    collisions.sort(key=lambda item: (-item["similarity"], item["first"]["id"], item["second"]["id"]))
    return {
        "schema_version": 1,
        "threshold": threshold,
        "screen_samples": len(samples),
        "potential_collisions": len(collisions),
        "note": "Static worst-case diagnostic; runtime collisions also depend on cache contents and insertion order.",
        "collisions": collisions,
    }


def main() -> int:
    _configure_console_utf8()
    args = build_parser().parse_args()
    try:
        if args.command == "prepare":
            _prepare(args)
        elif args.command == "inventory":
            lock, _, _ = _load_lock(args)
            _print_inventory(inventory(lock))
        elif args.command == "validate":
            lock, _, _ = _load_lock(args)
            print(f"valid corpus fingerprint: {fingerprint(lock)}")
        elif args.command == "run":
            _run(args)
        elif args.command == "score":
            _score(args)
        elif args.command == "compare":
            _comparison(args)
        elif args.command == "matrix":
            _matrix(args)
        elif args.command == "blind-packet":
            report = create_blind_packet(
                load_json(args.baseline),
                load_json(args.candidate),
                packet_path=args.packet,
                key_path=args.key,
                track=args.track,
                limit=args.limit,
                seed=args.seed,
            )
            print(f"wrote {report['rows']} blind rows to {report['packet']}")
            print(f"keep the model key separate from reviewers: {report['key']}")
        elif args.command == "blind-score":
            report = score_blind_packet(args.packet, load_json(args.key))
            write_json(args.output, report)
            print(f"scored {report['judgments']} judgments; wrote {args.output}")
        elif args.command == "reference-packet":
            lock, _, _ = _load_lock(args)
            count = create_reference_packet(lock, packet_path=args.packet, limit=args.limit, seed=args.seed)
            print(f"wrote {count} pre-output reference review rows to {args.packet}")
        elif args.command == "cache-audit":
            lock, _, _ = _load_lock(args)
            report = _cache_audit(lock, args.threshold)
            if args.output:
                write_json(args.output, report)
                print(f"wrote {args.output}")
            print(f"potential fuzzy-cache collisions: {report['potential_collisions']}")
        return 0
    except BenchmarkError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as exc:
        print(f"error: subprocess failed with exit code {exc.returncode}", file=sys.stderr)
        return exc.returncode or 1


if __name__ == "__main__":
    raise SystemExit(main())
