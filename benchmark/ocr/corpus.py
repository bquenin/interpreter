"""Acquire and validate the local real-screenshot OCR corpus."""

from __future__ import annotations

import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from benchlib import (
    BenchmarkError,
    manifest_fingerprint,
    select_samples,
    sha256_file,
    validate_manifest,
    write_json,
)

USER_AGENT = "InterpreterOCRBenchmark/1.0 (https://github.com/bquenin/interpreter)"


def _safe_target(data_dir: Path, relative: str) -> Path:
    root = data_dir.resolve()
    target = (data_dir / relative).resolve()
    if not target.is_relative_to(root):
        raise BenchmarkError(f"Corpus path escapes data directory: {relative}")
    return target


def _download(url: str, destination: Path, expected_sha256: str | None) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and (expected_sha256 is None or sha256_file(destination) == expected_sha256):
        return

    partial = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=90) as response, partial.open("wb") as handle:
            while chunk := response.read(1024 * 1024):
                handle.write(chunk)
    except (OSError, urllib.error.URLError) as exc:
        if partial.exists():
            partial.unlink()
        raise BenchmarkError(f"Could not download {url}: {exc}") from exc

    actual = sha256_file(partial)
    if expected_sha256 and actual != expected_sha256:
        partial.unlink()
        raise BenchmarkError(
            f"SHA-256 mismatch for {url}: expected {expected_sha256}, got {actual}. "
            "The upstream asset may have changed."
        )
    partial.replace(destination)


def _extract_git(source: dict[str, Any], destination: Path, expected_sha256: str | None, repo_root: Path) -> None:
    if destination.exists() and expected_sha256 and sha256_file(destination) == expected_sha256:
        return
    object_name = f"{source['ref']}:{source['git_path']}"
    try:
        content = subprocess.check_output(["git", "show", object_name], cwd=repo_root)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BenchmarkError(
            f"Could not read {object_name}. Fetch the benchmark branch/history from origin and retry."
        ) from exc
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    if expected_sha256 and sha256_file(destination) != expected_sha256:
        destination.unlink()
        raise BenchmarkError(f"SHA-256 mismatch while extracting {object_name}")


def prepare_corpus(
    manifest: dict[str, Any],
    manifest_path: Path,
    data_dir: Path,
    repo_root: Path,
    suites: list[str] | None = None,
    roles: list[str] | None = None,
) -> dict[str, Any]:
    errors = validate_manifest(manifest)
    if errors:
        raise BenchmarkError("Manifest validation failed:\n- " + "\n- ".join(errors))

    selected = select_samples(manifest, suites=suites, roles=roles, include_unscored=True)
    if not selected:
        raise BenchmarkError("No corpus samples matched the requested filters")

    lock: dict[str, Any] = {
        "schema_version": 1,
        "manifest": str(manifest_path.resolve()),
        "manifest_sha256": manifest_fingerprint(manifest),
        "files": {},
    }

    try:
        from PIL import Image
    except ImportError as exc:
        raise BenchmarkError("Pillow is required to inspect corpus images") from exc

    for index, sample in enumerate(selected, start=1):
        destination = _safe_target(data_dir, sample["path"])
        source = sample["source"]
        expected_hash = sample.get("image", {}).get("sha256")
        print(f"[{index:02d}/{len(selected):02d}] {sample['id']}")
        if source["kind"] == "url":
            _download(source["url"], destination, expected_hash)
        else:
            _extract_git(source, destination, expected_hash, repo_root)

        try:
            with Image.open(destination) as image:
                width, height = image.size
                image.verify()
        except OSError as exc:
            raise BenchmarkError(f"Invalid image for sample {sample['id']}: {destination}") from exc

        expected_image = sample.get("image", {})
        if expected_image.get("width") and width != expected_image["width"]:
            raise BenchmarkError(f"Width mismatch for {sample['id']}: expected {expected_image['width']}, got {width}")
        if expected_image.get("height") and height != expected_image["height"]:
            raise BenchmarkError(
                f"Height mismatch for {sample['id']}: expected {expected_image['height']}, got {height}"
            )

        lock["files"][sample["id"]] = {
            "path": sample["path"],
            "sha256": sha256_file(destination),
            "width": width,
            "height": height,
            "bytes": destination.stat().st_size,
        }

    data_dir.mkdir(parents=True, exist_ok=True)
    write_json(data_dir / "corpus.lock.json", lock)
    return lock


def validate_local_corpus(
    manifest: dict[str, Any],
    data_dir: Path,
    suites: list[str] | None = None,
    roles: list[str] | None = None,
) -> dict[str, Any]:
    errors = validate_manifest(manifest)
    selected = select_samples(manifest, suites=suites, roles=roles, include_unscored=True)
    missing = []
    mismatched = []
    for sample in selected:
        path = _safe_target(data_dir, sample["path"])
        if not path.is_file():
            missing.append(sample["id"])
            continue
        expected_hash = sample.get("image", {}).get("sha256")
        if expected_hash and sha256_file(path) != expected_hash:
            mismatched.append(sample["id"])
    return {
        "valid": not errors and not missing and not mismatched,
        "manifest_errors": errors,
        "selected": len(selected),
        "missing": missing,
        "hash_mismatches": mismatched,
    }
