#!/usr/bin/env python3
"""Sweep different image widths to find optimal preprocessing size.

Uses best model combo (v3_mobile + en_v3_mobile) and tests widths from 1700 to 300.
"""

import json
import os
import time
from pathlib import Path

import numpy as np
from PIL import Image

# Best models from previous benchmark
DET_MODEL = "PP-OCRv3_mobile_det"
REC_MODEL = "en_PP-OCRv3_mobile_rec"

# Width sweep parameters
WIDTHS = list(range(1000, 300, -100))  # 1000, 900, ..., 400

# Use all images
SAMPLE_IMAGES = None  # None = use all images


def load_ground_truth(dataset_path: Path) -> dict:
    """Load ground truth data from JSON file."""
    gt_path = dataset_path / "ground_truth.json"
    with open(gt_path) as f:
        data = json.load(f)
    # Filter to sample images if specified
    if SAMPLE_IMAGES is not None:
        return {k: v for k, v in data.items() if k in SAMPLE_IMAGES}
    return data


def load_image_as_array(image_path: Path, target_width: int | None = None) -> np.ndarray:
    """Load image as numpy array with optional resize."""
    img = Image.open(image_path).convert("RGB")

    if target_width is not None and img.width != target_width:
        ratio = target_width / img.width
        new_height = int(img.height * ratio)
        img = img.resize((target_width, new_height), Image.Resampling.LANCZOS)

    return np.array(img)


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


def extract_text_from_result(ocr_result) -> str:
    """Extract text from PaddleOCR 3.x result, sorted by reading order."""
    if not ocr_result:
        return ""

    text_items = []

    for res in ocr_result:
        if 'rec_texts' not in res or not res['rec_texts']:
            continue

        texts = res['rec_texts']
        polys = res.get('rec_polys', [])

        for i, text in enumerate(texts):
            if i < len(polys) and len(polys[i]) >= 4:
                bbox = polys[i]
                min_y = min(point[1] for point in bbox)
                min_x = min(point[0] for point in bbox)
                text_items.append((min_y, min_x, text))

    if not text_items:
        return ""

    text_items.sort(key=lambda item: item[0])

    line_threshold = 30
    lines = []
    current_line = [text_items[0]]

    for item in text_items[1:]:
        if abs(item[0] - current_line[0][0]) <= line_threshold:
            current_line.append(item)
        else:
            lines.append(current_line)
            current_line = [item]
    lines.append(current_line)

    result_texts = []
    for line in lines:
        line.sort(key=lambda item: item[1])
        result_texts.extend(item[2] for item in line)

    return " ".join(result_texts)


def test_width(ocr, dataset_path: Path, ground_truth: dict, width: int) -> dict:
    """Test OCR at a specific width."""
    results = []
    total_time = 0

    for filename, gt_data in ground_truth.items():
        image_path = dataset_path / filename
        if not image_path.exists():
            continue

        img_array = load_image_as_array(image_path, target_width=width)

        start_time = time.perf_counter()
        ocr_result = ocr.predict(img_array)
        elapsed = time.perf_counter() - start_time
        total_time += elapsed

        ocr_text = extract_text_from_result(ocr_result)
        gt_text = gt_data["text"]

        # Calculate similarity
        ocr_norm = ocr_text.lower().strip()
        gt_norm = gt_text.lower().strip()
        edit_dist = levenshtein(ocr_norm, gt_norm)
        max_len = max(len(ocr_norm), len(gt_norm), 1)
        similarity = 1 - (edit_dist / max_len)

        results.append({
            "filename": filename,
            "time_ms": elapsed * 1000,
            "similarity": similarity,
        })

    avg_time = total_time / len(results) * 1000
    avg_similarity = sum(r["similarity"] for r in results) / len(results)

    return {
        "width": width,
        "avg_time_ms": avg_time,
        "avg_similarity": avg_similarity,
        "results": results,
    }


def main():
    os.environ["DISABLE_MODEL_SOURCE_CHECK"] = "True"

    from paddleocr import PaddleOCR

    benchmark_dir = Path(__file__).parent
    dataset_path = benchmark_dir / "dataset"

    print("Width Sweep Benchmark")
    print("=" * 70)
    print(f"Detection: {DET_MODEL}")
    print(f"Recognition: {REC_MODEL}")
    print(f"Images: {'all' if SAMPLE_IMAGES is None else len(SAMPLE_IMAGES)}")
    print(f"Widths to test: {len(WIDTHS)} ({max(WIDTHS)} to {min(WIDTHS)})")
    print("=" * 70)

    ground_truth = load_ground_truth(dataset_path)

    # Initialize OCR once
    print("\nInitializing OCR...")
    ocr = PaddleOCR(
        text_detection_model_name=DET_MODEL,
        text_recognition_model_name=REC_MODEL,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )

    # Test each width
    all_results = []
    print(f"\n{'Width':<8} {'Time (ms)':<12} {'Similarity':<12}")
    print("-" * 32)

    for width in WIDTHS:
        result = test_width(ocr, dataset_path, ground_truth, width)
        all_results.append(result)
        print(f"{width:<8} {result['avg_time_ms']:<12.0f} {result['avg_similarity']:<12.1%}")

    # Find best
    best_by_sim = max(all_results, key=lambda x: x["avg_similarity"])
    best_by_speed = min(all_results, key=lambda x: x["avg_time_ms"])

    # Find best balance (highest similarity with reasonable speed)
    # Score = similarity - (time_penalty), where time_penalty increases for slower times
    min_time = min(r["avg_time_ms"] for r in all_results)
    for r in all_results:
        time_penalty = (r["avg_time_ms"] - min_time) / 1000 * 0.05  # 5% penalty per second slower
        r["score"] = r["avg_similarity"] - time_penalty

    best_balanced = max(all_results, key=lambda x: x["score"])

    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(f"Best accuracy:  {best_by_sim['width']}px ({best_by_sim['avg_similarity']:.1%}, {best_by_sim['avg_time_ms']:.0f}ms)")
    print(f"Fastest:        {best_by_speed['width']}px ({best_by_speed['avg_similarity']:.1%}, {best_by_speed['avg_time_ms']:.0f}ms)")
    print(f"Best balanced:  {best_balanced['width']}px ({best_balanced['avg_similarity']:.1%}, {best_balanced['avg_time_ms']:.0f}ms)")

    # Save results
    output_path = benchmark_dir / "width_sweep_results.json"
    summary = [{k: v for k, v in r.items() if k != "results"} for r in all_results]
    with open(output_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSaved to: {output_path}")


if __name__ == "__main__":
    main()
