#!/usr/bin/env python3
"""Benchmark MeikiOCR preprocessing on Japanese game text.

Tests whether the LANCZOS 700px + Gaussian blur preprocessing
(optimized for PaddleOCR) also helps MeikiOCR for Japanese text.
"""

import json
import time
from pathlib import Path

import cv2
import numpy as np
from meikiocr import MeikiOCR
from PIL import Image


# Preprocessing configurations to test
PREPROCESSING_CONFIGS = [
    {"name": "raw", "target_width": None, "blur_size": 0, "upscale": None},
    {"name": "old_interpreter_300_nearest_4x", "target_width": 300, "blur_size": 0, "upscale": 4},  # Old approach: 300px → 4x NEAREST → 1200px
    {"name": "lanczos_700_blur5", "target_width": 700, "blur_size": 5, "upscale": None},  # PaddleOCR optimal
    {"name": "lanczos_700_no_blur", "target_width": 700, "blur_size": 0, "upscale": None},  # MeikiOCR optimal candidate
]


def load_ground_truth(dataset_path: Path) -> dict:
    """Load ground truth data from JSON file."""
    gt_path = dataset_path / "ground_truth.json"
    with open(gt_path, encoding="utf-8") as f:
        return json.load(f)


def load_image_as_array(
    image_path: Path,
    target_width: int | None = None,
    blur_size: int = 0,
    upscale: int | None = None,
) -> np.ndarray:
    """Load image as numpy array (BGR format for MeikiOCR).

    Args:
        image_path: Path to image file
        target_width: Target width for LANCZOS resize (None = no resize)
        blur_size: Gaussian blur kernel size (0 = no blur)
        upscale: NEAREST neighbor upscale factor after resize (None = no upscale)
                 Used for old interpreter approach: 300px → 4x NEAREST → 1200px
    """
    img = Image.open(image_path).convert("RGB")

    if target_width is not None and img.width != target_width:
        ratio = target_width / img.width
        new_height = int(img.height * ratio)
        img = img.resize((target_width, new_height), Image.Resampling.LANCZOS)

    # NEAREST upscale (old interpreter approach)
    if upscale is not None and upscale > 1:
        new_width = img.width * upscale
        new_height = img.height * upscale
        img = img.resize((new_width, new_height), Image.Resampling.NEAREST)

    # Convert to BGR for OpenCV/MeikiOCR
    rgb_array = np.array(img)
    bgr_array = cv2.cvtColor(rgb_array, cv2.COLOR_RGB2BGR)

    if blur_size > 0:
        bgr_array = cv2.GaussianBlur(bgr_array, (blur_size, blur_size), 0)

    return bgr_array


def levenshtein(s1: str, s2: str) -> int:
    """Calculate Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)

    prev_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row

    return prev_row[-1]


def calculate_similarity(ocr_text: str, ground_truth: str) -> float:
    """Calculate similarity between OCR output and ground truth."""
    # Normalize: remove spaces (Japanese doesn't use spaces)
    ocr_normalized = ocr_text.replace(" ", "").strip()
    gt_normalized = ground_truth.replace(" ", "").strip()

    if not gt_normalized:
        return 1.0 if not ocr_normalized else 0.0

    edit_distance = levenshtein(ocr_normalized, gt_normalized)
    max_len = max(len(ocr_normalized), len(gt_normalized))
    similarity = 1 - (edit_distance / max_len)

    return similarity


def extract_text_from_meiki_result(ocr_result: list[dict]) -> str:
    """Extract text from MeikiOCR result."""
    if not ocr_result:
        return ""

    texts = []
    for res in ocr_result:
        text = res.get("text", "")
        if text:
            texts.append(text)

    return " ".join(texts)


def run_benchmark(
    ocr: MeikiOCR,
    dataset_path: Path,
    ground_truth: dict,
    config: dict,
) -> dict:
    """Run OCR benchmark with specific preprocessing config."""
    results = []
    total_time = 0

    target_width = config.get("target_width")
    blur_size = config.get("blur_size", 0)
    upscale = config.get("upscale")

    for filename, gt_data in ground_truth.items():
        image_path = dataset_path / filename
        if not image_path.exists():
            continue

        img_array = load_image_as_array(image_path, target_width=target_width, blur_size=blur_size, upscale=upscale)

        try:
            start_time = time.perf_counter()
            ocr_result = ocr.run_ocr(img_array)
            elapsed = time.perf_counter() - start_time
            total_time += elapsed

            ocr_text = extract_text_from_meiki_result(ocr_result)
            gt_text = gt_data["text"]
            similarity = calculate_similarity(ocr_text, gt_text)

            results.append({
                "filename": filename,
                "time_ms": elapsed * 1000,
                "ocr_text": ocr_text,
                "gt_text": gt_text,
                "similarity": similarity,
            })

        except Exception as e:
            print(f"  {filename}: ERROR - {e}")

    if not results:
        return None

    avg_time = total_time / len(results) * 1000
    avg_similarity = sum(r["similarity"] for r in results) / len(results)

    return {
        "avg_time_ms": avg_time,
        "avg_similarity": avg_similarity,
        "results": results,
    }


def main():
    """Run the MeikiOCR Japanese preprocessing benchmark."""
    benchmark_dir = Path(__file__).parent
    dataset_path = benchmark_dir / "dataset_japanese"

    print("MeikiOCR Japanese Preprocessing Benchmark")
    print("=" * 70)
    print("Testing: Does LANCZOS+blur preprocessing help MeikiOCR for Japanese?")
    print("=" * 70)

    ground_truth = load_ground_truth(dataset_path)
    print(f"Ground truth entries: {len(ground_truth)}")

    print("\nInitializing MeikiOCR (Japanese)...")
    ocr = MeikiOCR()  # Default is Japanese
    print(f"Provider: {ocr.active_provider}")

    all_results = {"configs": []}

    for config in PREPROCESSING_CONFIGS:
        config_name = config["name"]
        print(f"\n{'=' * 70}")
        print(f"Testing: preprocessing={config_name}")
        print("=" * 70)

        preprocess_desc = []
        if config.get("target_width"):
            preprocess_desc.append(f"LANCZOS to {config['target_width']}px")
        if config.get("upscale"):
            preprocess_desc.append(f"{config['upscale']}x NEAREST upscale")
        if config.get("blur_size", 0) > 0:
            preprocess_desc.append(f"blur {config['blur_size']}x{config['blur_size']}")
        print(f"Preprocessing: {' + '.join(preprocess_desc) if preprocess_desc else 'none (raw images)'}")

        metrics = run_benchmark(ocr, dataset_path, ground_truth, config)

        if metrics:
            # Print per-image results
            for r in metrics["results"]:
                print(f"  {r['filename']}: {r['time_ms']:.0f}ms, sim={r['similarity']:.2f}")

            result = {
                "preprocessing": config_name,
                "config": config,
                "avg_time_ms": metrics["avg_time_ms"],
                "avg_similarity": metrics["avg_similarity"],
            }
            all_results["configs"].append(result)
            print(f"\n=> Avg: {metrics['avg_time_ms']:.0f}ms, {metrics['avg_similarity']:.1%} similarity")

    # Summary
    print("\n" + "=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)
    print(f"{'Preprocessing':<30} {'Time':<10} {'Similarity':<12}")
    print("-" * 55)

    for r in sorted(all_results["configs"], key=lambda x: x["avg_similarity"], reverse=True):
        print(f"{r['preprocessing']:<30} {r['avg_time_ms']:<10.0f} {r['avg_similarity']:<12.1%}")

    if all_results["configs"]:
        best = max(all_results["configs"], key=lambda x: x["avg_similarity"])
        worst = min(all_results["configs"], key=lambda x: x["avg_similarity"])
        diff = best["avg_similarity"] - worst["avg_similarity"]
        print(f"\n>>> Best: {best['preprocessing']} ({best['avg_similarity']:.1%})")
        print(f">>> Improvement over worst: {diff:+.1%}")

    # Save results
    output_path = benchmark_dir / "meiki_japanese_results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"\nSaved to: {output_path}")


if __name__ == "__main__":
    main()
