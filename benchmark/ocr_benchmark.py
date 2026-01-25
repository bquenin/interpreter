#!/usr/bin/env python3
"""Benchmark script for PaddleOCR 3.x models.

Uses sequential evaluation:
1. Test all detection models with fixed recognition → pick best detection
2. Test all recognition models with best detection → pick best recognition
"""

import json
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


# Detection models (language-agnostic)
DETECTION_MODELS = [
    ("PP-OCRv4_mobile_det", "v4_mobile"),
    ("PP-OCRv4_server_det", "v4_server"),
    ("PP-OCRv3_mobile_det", "v3_mobile"),
    ("PP-OCRv3_server_det", "v3_server"),
]

# English recognition models (no server models exist for English)
RECOGNITION_MODELS = [
    ("en_PP-OCRv4_mobile_rec", "en_v4_mobile"),
    ("en_PP-OCRv3_mobile_rec", "en_v3_mobile"),
]

# Fixed models for sequential testing
FIXED_REC_MODEL = ("en_PP-OCRv4_mobile_rec", "en_v4_mobile")
FIXED_DET_MODEL = ("PP-OCRv4_mobile_det", "v4_mobile")  # Will be updated after phase 1

# Preprocessing options (optimized for pixel fonts)
TARGET_WIDTH = 700  # Resize images proportionally to this width (None = no resize)
GAUSSIAN_BLUR_SIZE = 5  # Gaussian blur kernel size (0 = no blur)


def load_ground_truth(dataset_path: Path) -> dict:
    """Load ground truth data from JSON file."""
    gt_path = dataset_path / "ground_truth.json"
    with open(gt_path) as f:
        return json.load(f)


def load_image_as_array(
    image_path: Path,
    target_width: int | None = None,
    blur_size: int = 0,
) -> np.ndarray:
    """Load image as numpy array (RGB format) with optional preprocessing.

    Args:
        image_path: Path to the image file
        target_width: If specified, resize image proportionally to this width
        blur_size: Gaussian blur kernel size (0 = no blur, must be odd if >0)
    """
    img = Image.open(image_path).convert("RGB")

    if target_width is not None and img.width != target_width:
        # Resize proportionally with LANCZOS
        ratio = target_width / img.width
        new_height = int(img.height * ratio)
        img = img.resize((target_width, new_height), Image.Resampling.LANCZOS)

    rgb_array = np.array(img)

    # Apply Gaussian blur to smooth pixel edges (helps recognition)
    if blur_size > 0:
        rgb_array = cv2.GaussianBlur(rgb_array, (blur_size, blur_size), 0)

    return rgb_array


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


def calculate_accuracy(ocr_text: str, ground_truth: str) -> dict:
    """Calculate accuracy metrics between OCR output and ground truth."""
    ocr_normalized = ocr_text.lower().strip()
    gt_normalized = ground_truth.lower().strip()

    # Word-level accuracy
    ocr_words = set(ocr_normalized.split())
    gt_words = set(gt_normalized.split())
    word_overlap = len(ocr_words & gt_words)
    word_total = len(gt_words) if gt_words else 1
    word_accuracy = word_overlap / word_total

    # Levenshtein-based similarity
    edit_distance = levenshtein(ocr_normalized, gt_normalized)
    max_len = max(len(ocr_normalized), len(gt_normalized), 1)
    similarity = 1 - (edit_distance / max_len)

    return {
        "word_accuracy": word_accuracy,
        "edit_distance": edit_distance,
        "similarity": similarity,
    }


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

    # Sort by reading order: group by approximate line (Y), then sort by X
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


def run_single_test(
    ocr,
    dataset_path: Path,
    ground_truth: dict,
    target_width: int | None = None,
) -> dict:
    """Run OCR on all images and return metrics."""
    results = []
    total_ocr_time = 0

    for filename, gt_data in ground_truth.items():
        image_path = dataset_path / filename
        if not image_path.exists():
            continue

        img_array = load_image_as_array(image_path, target_width=target_width, blur_size=GAUSSIAN_BLUR_SIZE)

        try:
            start_time = time.perf_counter()
            ocr_result = ocr.predict(img_array)
            elapsed = time.perf_counter() - start_time
            total_ocr_time += elapsed

            ocr_text = extract_text_from_result(ocr_result)
            gt_text = gt_data["text"]
            accuracy = calculate_accuracy(ocr_text, gt_text)

            results.append({
                "filename": filename,
                "time_ms": elapsed * 1000,
                "ocr_text": ocr_text,
                "gt_text": gt_text,
                **accuracy,
            })

            print(f"  {filename}: {elapsed*1000:.0f}ms, sim={accuracy['similarity']:.2f}")

        except Exception as e:
            print(f"  {filename}: ERROR - {e}")

    if not results:
        return None

    avg_time = total_ocr_time / len(results) * 1000
    avg_similarity = sum(r["similarity"] for r in results) / len(results)
    avg_word_acc = sum(r["word_accuracy"] for r in results) / len(results)

    return {
        "avg_time_ms": avg_time,
        "avg_similarity": avg_similarity,
        "avg_word_accuracy": avg_word_acc,
        "results": results,
    }


def main():
    """Run the OCR benchmark with sequential evaluation."""
    import os
    os.environ["DISABLE_MODEL_SOURCE_CHECK"] = "True"

    from paddleocr import PaddleOCR

    benchmark_dir = Path(__file__).parent
    dataset_path = benchmark_dir / "dataset"

    print("PaddleOCR 3.x Benchmark - Sequential Evaluation")
    print("=" * 70)

    ground_truth = load_ground_truth(dataset_path)
    print(f"Ground truth entries: {len(ground_truth)}")
    preprocess_desc = []
    if TARGET_WIDTH:
        preprocess_desc.append(f"resize to {TARGET_WIDTH}px")
    if GAUSSIAN_BLUR_SIZE > 0:
        preprocess_desc.append(f"blur {GAUSSIAN_BLUR_SIZE}x{GAUSSIAN_BLUR_SIZE}")
    print(f"Preprocessing: {' + '.join(preprocess_desc) if preprocess_desc else 'none (raw images)'}")

    all_results = {
        "detection_phase": [],
        "recognition_phase": [],
    }

    # =========================================================================
    # PHASE 1: Test all detection models with fixed recognition
    # =========================================================================
    print("\n" + "=" * 70)
    print(f"PHASE 1: Detection Models (fixed rec: {FIXED_REC_MODEL[1]})")
    print("=" * 70)

    detection_results = []

    for det_model, det_label in DETECTION_MODELS:
        print(f"\nTesting: {det_label}")
        print("-" * 40)

        try:
            init_start = time.perf_counter()
            ocr = PaddleOCR(
                text_detection_model_name=det_model,
                text_recognition_model_name=FIXED_REC_MODEL[0],
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
            init_time = time.perf_counter() - init_start
            print(f"Init: {init_time:.1f}s")

            metrics = run_single_test(ocr, dataset_path, ground_truth, target_width=TARGET_WIDTH)
            if metrics:
                result = {
                    "det_model": det_model,
                    "det_label": det_label,
                    "rec_model": FIXED_REC_MODEL[0],
                    **{k: v for k, v in metrics.items() if k != "results"},
                }
                detection_results.append(result)
                print(f"=> Avg: {metrics['avg_time_ms']:.0f}ms, {metrics['avg_similarity']:.1%} sim")

        except Exception as e:
            print(f"Failed: {e}")

    # Sort and display detection results
    detection_results.sort(key=lambda x: x["avg_similarity"], reverse=True)
    all_results["detection_phase"] = detection_results

    print("\n" + "-" * 70)
    print("DETECTION RESULTS (sorted by similarity)")
    print("-" * 70)
    print(f"{'Model':<20} {'Time':<10} {'Similarity':<12} {'Word Acc':<10}")
    for r in detection_results:
        print(f"{r['det_label']:<20} {r['avg_time_ms']:<10.0f} {r['avg_similarity']:<12.1%} {r['avg_word_accuracy']:<10.1%}")

    best_det = detection_results[0] if detection_results else None
    if best_det:
        print(f"\n>>> Best detection: {best_det['det_label']} ({best_det['avg_similarity']:.1%})")

    # =========================================================================
    # PHASE 2: Test all recognition models with best detection
    # =========================================================================
    if not best_det:
        print("\nNo detection results, skipping phase 2")
        return

    best_det_model = (best_det["det_model"], best_det["det_label"])

    print("\n" + "=" * 70)
    print(f"PHASE 2: Recognition Models (fixed det: {best_det_model[1]})")
    print("=" * 70)

    recognition_results = []

    for rec_model, rec_label in RECOGNITION_MODELS:
        print(f"\nTesting: {rec_label}")
        print("-" * 40)

        try:
            init_start = time.perf_counter()
            ocr = PaddleOCR(
                text_detection_model_name=best_det_model[0],
                text_recognition_model_name=rec_model,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
            init_time = time.perf_counter() - init_start
            print(f"Init: {init_time:.1f}s")

            metrics = run_single_test(ocr, dataset_path, ground_truth, target_width=TARGET_WIDTH)
            if metrics:
                result = {
                    "rec_model": rec_model,
                    "rec_label": rec_label,
                    "det_model": best_det_model[0],
                    **{k: v for k, v in metrics.items() if k != "results"},
                }
                recognition_results.append(result)
                print(f"=> Avg: {metrics['avg_time_ms']:.0f}ms, {metrics['avg_similarity']:.1%} sim")

        except Exception as e:
            print(f"Failed: {e}")

    # Sort and display recognition results
    recognition_results.sort(key=lambda x: x["avg_similarity"], reverse=True)
    all_results["recognition_phase"] = recognition_results

    print("\n" + "-" * 70)
    print("RECOGNITION RESULTS (sorted by similarity)")
    print("-" * 70)
    print(f"{'Model':<20} {'Time':<10} {'Similarity':<12} {'Word Acc':<10}")
    for r in recognition_results:
        print(f"{r['rec_label']:<20} {r['avg_time_ms']:<10.0f} {r['avg_similarity']:<12.1%} {r['avg_word_accuracy']:<10.1%}")

    best_rec = recognition_results[0] if recognition_results else None
    if best_rec:
        print(f"\n>>> Best recognition: {best_rec['rec_label']} ({best_rec['avg_similarity']:.1%})")

    # =========================================================================
    # FINAL SUMMARY
    # =========================================================================
    print("\n" + "=" * 70)
    print("FINAL RECOMMENDATION")
    print("=" * 70)
    if best_det and best_rec:
        print(f"Detection:   {best_det['det_label']}")
        print(f"Recognition: {best_rec['rec_label']}")
        print(f"Similarity:  {best_rec['avg_similarity']:.1%}")
        print(f"Avg time:    {best_rec['avg_time_ms']:.0f}ms")

    # Save results
    output_path = benchmark_dir / "benchmark_results.json"
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nSaved to: {output_path}")


if __name__ == "__main__":
    main()
