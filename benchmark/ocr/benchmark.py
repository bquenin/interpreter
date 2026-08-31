#!/usr/bin/env python3
"""CLI for preparing, running, and comparing the Interpreter OCR benchmark."""

from __future__ import annotations

import argparse
import importlib.metadata
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from benchlib import (
    DEFAULT_DATA_DIR,
    DEFAULT_MANIFEST,
    DEFAULT_RESULTS_DIR,
    BenchmarkError,
    load_json,
    validate_manifest,
    write_json,
)
from corpus import prepare_corpus, validate_local_corpus
from runner import compare_results, format_summary, run_benchmark


def _path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _add_corpus_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--manifest", type=_path, default=DEFAULT_MANIFEST, help="Corpus manifest JSON")
    parser.add_argument("--data-dir", type=_path, default=DEFAULT_DATA_DIR, help="Ignored local corpus directory")
    parser.add_argument("--suite", action="append", dest="suites", help="Select a suite; repeat for multiple suites")
    parser.add_argument("--role", action="append", dest="roles", help="Select a corpus role; repeat for multiple roles")


def _add_run_arguments(parser: argparse.ArgumentParser, include_label: bool = True) -> None:
    _add_corpus_arguments(parser)
    if include_label:
        parser.add_argument("--label", required=True, help="Human-readable model/run label")
    parser.add_argument("--repeats", type=int, default=5, help="Timed repetitions per image (default: 5)")
    parser.add_argument("--warmups", type=int, default=1, help="Untimed warm-up passes (default: 1)")
    parser.add_argument("--seed", type=int, default=1729, help="Deterministic sample-order seed")
    parser.add_argument("--confidence", type=float, default=0.6, help="Interpreter line confidence threshold")
    parser.add_argument(
        "--include-unscored",
        action="store_true",
        help="Run draft/unscored stress images for latency and diagnostics; never include them in CER",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    inventory = subparsers.add_parser("inventory", help="Summarize corpus composition and annotation readiness")
    inventory.add_argument("--manifest", type=_path, default=DEFAULT_MANIFEST)

    prepare = subparsers.add_parser("prepare", help="Download or extract the local ignored screenshot corpus")
    _add_corpus_arguments(prepare)

    validate = subparsers.add_parser("validate", help="Validate manifest and any selected local files")
    _add_corpus_arguments(validate)

    run = subparsers.add_parser("run", help="Run the exact production OCR pipeline in the current environment")
    _add_run_arguments(run)
    run.add_argument("--output", type=_path, required=True, help="Result JSON path")

    compare = subparsers.add_parser("compare", help="Compare paired baseline and candidate result JSON")
    compare.add_argument("baseline", type=_path)
    compare.add_argument("candidate", type=_path)
    compare.add_argument("--output", type=_path, help="Comparison JSON path")
    compare.add_argument("--bootstrap-iterations", type=int, default=10_000)
    compare.add_argument("--bootstrap-seed", type=int, default=1729)
    compare.add_argument("--min-real-samples", type=int, default=100)
    compare.add_argument("--min-games", type=int, default=5)
    compare.add_argument("--max-p95-ms", type=float, default=500.0)
    compare.add_argument("--max-latency-regression", type=float, default=0.25)

    matrix = subparsers.add_parser(
        "matrix",
        help="Safely benchmark installed baseline vs an isolated MeikiOCR-compatible candidate",
    )
    _add_run_arguments(matrix, include_label=False)
    matrix.add_argument(
        "--candidate",
        default="meikiocr==0.3.4",
        help="uv package spec for the isolated candidate (default: meikiocr==0.3.4)",
    )
    matrix.add_argument("--baseline-label", help="Override baseline label")
    matrix.add_argument("--candidate-label", help="Override candidate label")
    matrix.add_argument("--results-dir", type=_path, default=DEFAULT_RESULTS_DIR)
    matrix.add_argument(
        "--baseline-online",
        action="store_true",
        help="Allow baseline model downloads. Default is offline to pin the already-installed model files.",
    )
    matrix.add_argument("--bootstrap-iterations", type=int, default=10_000)
    matrix.add_argument("--min-real-samples", type=int, default=100)
    matrix.add_argument("--min-games", type=int, default=5)
    matrix.add_argument("--max-p95-ms", type=float, default=500.0)
    matrix.add_argument("--max-latency-regression", type=float, default=0.25)
    return parser


def _inventory(manifest: dict) -> None:
    errors = validate_manifest(manifest)
    if errors:
        raise BenchmarkError("Manifest validation failed:\n- " + "\n- ".join(errors))
    samples = manifest["samples"]
    print(f"samples: {len(samples)}")
    for field in ("role",):
        values = sorted({sample[field] for sample in samples})
        for value in values:
            print(f"  {field}={value}: {sum(sample[field] == value for sample in samples)}")
    statuses = sorted({sample["annotation"]["status"] for sample in samples})
    for status in statuses:
        print(f"  annotation={status}: {sum(sample['annotation']['status'] == status for sample in samples)}")
    suites = sorted({suite for sample in samples for suite in sample["suites"]})
    for suite in suites:
        print(f"  suite={suite}: {sum(suite in sample['suites'] for sample in samples)}")


def _print_comparison(comparison: dict) -> None:
    paired = comparison["paired_cer"]
    lower, upper = paired["ci95"]
    delta = paired["delta"]
    print(f"baseline  {format_summary(comparison['baseline_summary'])}")
    print(f"candidate {format_summary(comparison['candidate_summary'])}")
    if delta is None:
        print("paired CER delta: n/a")
    else:
        print(f"paired CER delta (candidate - baseline): {delta:+.4%} (95% CI {lower:+.4%} to {upper:+.4%})")
    print(
        f"paired images: {comparison['candidate_wins']} wins / "
        f"{comparison['candidate_losses']} losses / {comparison['ties']} ties"
    )
    print(f"statistical outcome: {comparison['statistical_outcome']}")
    gate = comparison["promotion_gate"]
    print(f"promotion gate: {'READY' if gate['ready'] else 'NOT READY'}")
    for blocker in gate["blockers"]:
        print(f"  - {blocker}")


def _run_command(args: argparse.Namespace) -> dict:
    manifest = load_json(args.manifest)
    result = run_benchmark(
        manifest=manifest,
        manifest_path=args.manifest,
        data_dir=args.data_dir,
        repo_root=Path(__file__).resolve().parents[2],
        label=args.label,
        suites=args.suites,
        roles=args.roles,
        repeats=args.repeats,
        warmups=args.warmups,
        seed=args.seed,
        confidence=args.confidence,
        include_unscored=args.include_unscored,
    )
    write_json(args.output, result)
    print(format_summary(result["summary"]["overall"]))
    print(f"wrote {args.output}")
    return result


def _comparison_from_args(args: argparse.Namespace) -> dict:
    comparison = compare_results(
        load_json(args.baseline),
        load_json(args.candidate),
        bootstrap_iterations=args.bootstrap_iterations,
        bootstrap_seed=getattr(args, "bootstrap_seed", 1729),
        min_real_samples=args.min_real_samples,
        min_games=args.min_games,
        max_p95_ms=args.max_p95_ms,
        max_latency_regression=args.max_latency_regression,
    )
    output = args.output or args.candidate.with_name(f"comparison-{args.baseline.stem}-vs-{args.candidate.stem}.json")
    write_json(output, comparison)
    _print_comparison(comparison)
    print(f"wrote {output}")
    return comparison


def _safe_slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-")[:80] or "candidate"


def _matrix(args: argparse.Namespace) -> None:
    uv = shutil.which("uv")
    if not uv:
        raise BenchmarkError("uv is required for an isolated candidate run")

    # Keep the default focused on scoreable, real retro-game screenshots.
    # Passing --suite explicitly replaces it.
    suites = args.suites or ["legacy-smoke", "retro-real", "retro-pc"]
    manifest = load_json(args.manifest)
    print("preparing corpus")
    prepare_corpus(
        manifest,
        args.manifest,
        args.data_dir,
        Path(__file__).resolve().parents[2],
        suites=suites,
        roles=args.roles,
    )

    try:
        baseline_version = importlib.metadata.version("meikiocr")
    except importlib.metadata.PackageNotFoundError as exc:
        raise BenchmarkError(
            "Run matrix from the installed Interpreter environment containing the current meikiocr"
        ) from exc

    timestamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    args.results_dir.mkdir(parents=True, exist_ok=True)
    baseline_label = args.baseline_label or f"installed-meikiocr-{baseline_version}"
    candidate_label = args.candidate_label or args.candidate
    baseline_path = args.results_dir / f"{timestamp}-baseline-{_safe_slug(baseline_label)}.json"
    candidate_path = args.results_dir / f"{timestamp}-candidate-{_safe_slug(candidate_label)}.json"
    comparison_path = args.results_dir / f"{timestamp}-comparison.json"

    common = [
        "--manifest",
        str(args.manifest),
        "--data-dir",
        str(args.data_dir),
        "--repeats",
        str(args.repeats),
        "--warmups",
        str(args.warmups),
        "--seed",
        str(args.seed),
        "--confidence",
        str(args.confidence),
    ]
    for suite in suites:
        common.extend(["--suite", suite])
    for role in args.roles or []:
        common.extend(["--role", role])
    if args.include_unscored:
        common.append("--include-unscored")

    script = str(Path(__file__).resolve())
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"

    baseline_environment = environment.copy()
    if not args.baseline_online:
        baseline_environment["HF_HUB_OFFLINE"] = "1"
    print(f"running baseline in place: {baseline_label}")
    subprocess.run(
        [sys.executable, script, "run", "--label", baseline_label, "--output", str(baseline_path), *common],
        check=True,
        cwd=Path(__file__).resolve().parents[2],
        env=baseline_environment,
    )

    candidate_environment = environment.copy()
    candidate_environment.pop("HF_HUB_OFFLINE", None)
    candidate_environment["HF_HOME"] = str(
        (Path(__file__).resolve().parent / ".cache" / "huggingface" / _safe_slug(args.candidate)).resolve()
    )
    print(f"running isolated candidate: {candidate_label}")
    subprocess.run(
        [
            uv,
            "run",
            "--isolated",
            "--no-project",
            "--with",
            args.candidate,
            "python",
            script,
            "run",
            "--label",
            candidate_label,
            "--output",
            str(candidate_path),
            *common,
        ],
        check=True,
        cwd=Path(__file__).resolve().parents[2],
        env=candidate_environment,
    )

    comparison = compare_results(
        load_json(baseline_path),
        load_json(candidate_path),
        bootstrap_iterations=args.bootstrap_iterations,
        min_real_samples=args.min_real_samples,
        min_games=args.min_games,
        max_p95_ms=args.max_p95_ms,
        max_latency_regression=args.max_latency_regression,
    )
    write_json(comparison_path, comparison)
    _print_comparison(comparison)
    print(f"baseline:   {baseline_path}")
    print(f"candidate:  {candidate_path}")
    print(f"comparison: {comparison_path}")


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "inventory":
            _inventory(load_json(args.manifest))
        elif args.command == "prepare":
            lock = prepare_corpus(
                load_json(args.manifest),
                args.manifest,
                args.data_dir,
                Path(__file__).resolve().parents[2],
                suites=args.suites,
                roles=args.roles,
            )
            print(f"prepared {len(lock['files'])} images under {args.data_dir}")
        elif args.command == "validate":
            report = validate_local_corpus(load_json(args.manifest), args.data_dir, args.suites, args.roles)
            print(f"selected={report['selected']} valid={report['valid']}")
            for key in ("manifest_errors", "missing", "hash_mismatches"):
                if report[key]:
                    print(f"{key}: {report[key]}")
            if not report["valid"]:
                return 1
        elif args.command == "run":
            _run_command(args)
        elif args.command == "compare":
            _comparison_from_args(args)
        elif args.command == "matrix":
            _matrix(args)
        return 0
    except (BenchmarkError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
