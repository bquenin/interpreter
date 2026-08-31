"""Corpus acquisition and deterministic synthetic-image generation."""

from __future__ import annotations

import random
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


def _ensure_font(manifest: dict[str, Any], font_id: str, data_dir: Path) -> Path:
    fonts = manifest.get("resources", {}).get("fonts", {})
    if font_id not in fonts:
        raise BenchmarkError(f"Unknown generated-corpus font: {font_id}")
    font = fonts[font_id]
    destination = _safe_target(data_dir, f"_resources/fonts/{font['filename']}")
    _download(font["url"], destination, font["sha256"])
    return destination


def _make_background(canvas: tuple[int, int], style: str, seed: str):
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise BenchmarkError("Pillow is required to prepare the OCR corpus") from exc

    width, height = canvas
    rng = random.Random(seed)
    if style == "black":
        return Image.new("RGB", canvas, "#050609")

    image = Image.new("RGB", canvas, "#253047")
    draw = ImageDraw.Draw(image)
    if style == "gradient":
        for y in range(height):
            ratio = y / max(height - 1, 1)
            color = (
                int(28 + 38 * ratio),
                int(42 + 25 * ratio),
                int(74 + 20 * ratio),
            )
            draw.line((0, y, width, y), fill=color)
    else:
        # Deterministic, game-like scenery: sky, ground, distant architecture,
        # and characters. It is deliberately abstract so it contains no text.
        draw.rectangle((0, 0, width, int(height * 0.58)), fill="#36557b")
        draw.rectangle((0, int(height * 0.58), width, height), fill="#283628")
        for _ in range(18):
            x = rng.randrange(-width // 10, width)
            y = rng.randrange(height // 10, int(height * 0.72))
            w = rng.randrange(max(8, width // 30), max(16, width // 9))
            h = rng.randrange(max(8, height // 24), max(16, height // 5))
            color = rng.choice(["#445b6f", "#53684e", "#6d5840", "#273b4f"])
            draw.rectangle((x, y, x + w, y + h), fill=color, outline="#1c2730", width=max(1, width // 640))
        for _ in range(10):
            x = rng.randrange(width)
            y = rng.randrange(height // 8, int(height * 0.7))
            radius = rng.randrange(max(3, width // 160), max(5, width // 55))
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill="#b98c52")
    return image


def _draw_generated_sample(sample: dict[str, Any], manifest: dict[str, Any], data_dir: Path) -> dict[str, Any]:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise BenchmarkError("Pillow is required to generate the synthetic OCR corpus") from exc

    generator = sample["source"]["generator"]
    output_canvas = tuple(generator["canvas"])
    native_canvas = tuple(generator.get("native_canvas", output_canvas))
    image = _make_background(native_canvas, generator.get("background", "scene"), sample["id"])
    draw = ImageDraw.Draw(image)

    for box in generator.get("boxes", []):
        draw.rectangle(
            tuple(box["xy"]),
            fill=box.get("fill"),
            outline=box.get("outline"),
            width=box.get("width", 1),
        )

    regions = []
    font_cache: dict[tuple[str, int], Any] = {}
    for line in generator.get("lines", []):
        font_id = line.get("font", generator.get("font", "dotgothic16"))
        font_size = int(line["size"])
        cache_key = (font_id, font_size)
        if cache_key not in font_cache:
            font_path = _ensure_font(manifest, font_id, data_dir)
            font_cache[cache_key] = ImageFont.truetype(str(font_path), font_size)
        font = font_cache[cache_key]
        x, y = line["xy"]
        fill = line.get("fill", "#f7f7f2")
        stroke_width = int(line.get("stroke_width", 0))
        stroke_fill = line.get("stroke_fill", "#050505")
        direction = line.get("direction", "horizontal")
        text = line["text"]

        if direction == "vertical":
            spacing = int(line.get("spacing", round(font_size * 1.04)))
            boxes = []
            for index, character in enumerate(text):
                position = (x, y + index * spacing)
                draw.text(
                    position,
                    character,
                    font=font,
                    fill=fill,
                    stroke_width=stroke_width,
                    stroke_fill=stroke_fill,
                )
                boxes.append(draw.textbbox(position, character, font=font, stroke_width=stroke_width))
            bbox = [
                min(box[0] for box in boxes),
                min(box[1] for box in boxes),
                max(box[2] for box in boxes),
                max(box[3] for box in boxes),
            ]
        else:
            spacing = int(line.get("spacing", round(font_size * 0.2)))
            draw.multiline_text(
                (x, y),
                text,
                font=font,
                fill=fill,
                spacing=spacing,
                stroke_width=stroke_width,
                stroke_fill=stroke_fill,
            )
            bbox = list(draw.multiline_textbbox((x, y), text, font=font, spacing=spacing, stroke_width=stroke_width))
        regions.append({"text": text, "bbox": bbox, "direction": direction})

    if native_canvas != output_canvas:
        resampling_name = generator.get("resampling", "nearest").upper()
        resampling = getattr(Image.Resampling, resampling_name)
        scale_x = output_canvas[0] / native_canvas[0]
        scale_y = output_canvas[1] / native_canvas[1]
        image = image.resize(output_canvas, resample=resampling)
        for region in regions:
            x1, y1, x2, y2 = region["bbox"]
            region["bbox"] = [
                round(x1 * scale_x),
                round(y1 * scale_y),
                round(x2 * scale_x),
                round(y2 * scale_y),
            ]

    destination = _safe_target(data_dir, sample["path"])
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, format="PNG", optimize=False)
    return {"generated_regions": regions}


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
        extra: dict[str, Any] = {}
        print(f"[{index:02d}/{len(selected):02d}] {sample['id']}")
        if source["kind"] == "url":
            _download(source["url"], destination, expected_hash)
        elif source["kind"] == "git":
            _extract_git(source, destination, expected_hash, repo_root)
        else:
            extra = _draw_generated_sample(sample, manifest, data_dir)

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
            **extra,
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
