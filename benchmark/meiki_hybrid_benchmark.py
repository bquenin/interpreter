#!/usr/bin/env python3
"""Benchmark script for MeikiOCR multilingual fork.

Tests eriksonssilva's meikiocr fork which combines:
- MeikiOCR detection (game-optimized, language-agnostic)
- PaddleOCR ONNX recognition models (language-specific)

Fork: https://github.com/eriksonssilva/meikiocr/tree/meiki-multilingual
"""

import json
import time
from pathlib import Path

import cv2
import numpy as np
from meikiocr import MeikiOCR, LANGUAGE_MODELS
from PIL import Image


# Languages to test (from the fork's supported languages)
LANGUAGES_TO_TEST = [
    ("en", "English"),
    ("latin", "Latin (32 langs)"),
]

# Preprocessing configurations to test
PREPROCESSING_CONFIGS = [
    {"name": "raw", "target_width": None, "blur_size": 0},
    {"name": "paddle_optimized", "target_width": 700, "blur_size": 5},
]


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
    """Load image as numpy array (BGR format for OpenCV/MeikiOCR)."""
    img = Image.open(image_path).convert("RGB")

    if target_width is not None and img.width != target_width:
        ratio = target_width / img.width
        new_height = int(img.height * ratio)
        img = img.resize((target_width, new_height), Image.Resampling.LANCZOS)

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


def calculate_accuracy(ocr_text: str, ground_truth: str) -> dict:
    """Calculate accuracy metrics between OCR output and ground truth."""
    ocr_normalized = ocr_text.lower().strip()
    gt_normalized = ground_truth.lower().strip()

    ocr_words = set(ocr_normalized.split())
    gt_words = set(gt_normalized.split())
    word_overlap = len(ocr_words & gt_words)
    word_total = len(gt_words) if gt_words else 1
    word_accuracy = word_overlap / word_total

    edit_distance = levenshtein(ocr_normalized, gt_normalized)
    max_len = max(len(ocr_normalized), len(gt_normalized), 1)
    similarity = 1 - (edit_distance / max_len)

    return {
        "word_accuracy": word_accuracy,
        "edit_distance": edit_distance,
        "similarity": similarity,
    }


def extract_text_from_meiki_result(ocr_result: list[dict]) -> str:
    """Extract text from MeikiOCR result, sorted by reading order.

    MeikiOCR returns: [{'text': str, 'chars': [{'char': str, 'bbox': [...], 'conf': float}]}]
    """
    if not ocr_result:
        return ""

    text_items = []

    for res in ocr_result:
        text = res.get('text', '')
        if not text:
            continue

        # Get bounding box from chars if available
        chars = res.get('chars', [])
        if chars and chars[0].get('bbox'):
            bbox = chars[0]['bbox']
            if len(bbox) >= 4:
                min_y = bbox[1]
                min_x = bbox[0]
                text_items.append((min_y, min_x, text))
        else:
            # Fallback: just append text
            text_items.append((0, 0, text))

    if not text_items:
        return ""

    # Sort by reading order (top-to-bottom, left-to-right)
    text_items.sort(key=lambda item: (item[0], item[1]))

    # Group into lines
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


def run_single_test_with_config(
    ocr: MeikiOCR,
    dataset_path: Path,
    ground_truth: dict,
    config: dict,
) -> dict:
    """Run OCR on all images with specific preprocessing config."""
    results = []
    total_ocr_time = 0

    target_width = config.get("target_width")
    blur_size = config.get("blur_size", 0)

    for filename, gt_data in ground_truth.items():
        image_path = dataset_path / filename
        if not image_path.exists():
            continue

        img_array = load_image_as_array(image_path, target_width=target_width, blur_size=blur_size)

        try:
            start_time = time.perf_counter()
            ocr_result = ocr.run_ocr(img_array)
            elapsed = time.perf_counter() - start_time
            total_ocr_time += elapsed

            ocr_text = extract_text_from_meiki_result(ocr_result)
            gt_text = gt_data["text"]
            accuracy = calculate_accuracy(ocr_text, gt_text)

            results.append({
                "filename": filename,
                "time_ms": elapsed * 1000,
                "ocr_text": ocr_text,
                "gt_text": gt_text,
                **accuracy,
            })

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
    """Run the MeikiOCR multilingual fork benchmark."""
    benchmark_dir = Path(__file__).parent
    dataset_path = benchmark_dir / "dataset"

    print("MeikiOCR Multilingual Fork Benchmark")
    print("=" * 70)
    print("Fork: eriksonssilva/meikiocr@meiki-multilingual")
    print("Approach: MeikiOCR detection + PaddleOCR ONNX recognition")
    print("=" * 70)

    # Show available languages
    print(f"\nAvailable languages in fork: {', '.join(sorted(LANGUAGE_MODELS.keys()))}")

    ground_truth = load_ground_truth(dataset_path)
    print(f"Ground truth entries: {len(ground_truth)}")

    all_results = {"models": []}

    # Test each language with each preprocessing config
    for lang_code, lang_name in LANGUAGES_TO_TEST:
        print(f"\nInitializing MeikiOCR for language='{lang_code}'...")
        try:
            ocr = MeikiOCR(language=lang_code)
            print(f"Provider: {ocr.active_provider}")
        except Exception as e:
            print(f"Failed to init: {e}")
            continue

        for config in PREPROCESSING_CONFIGS:
            config_name = config["name"]
            print(f"\n{'=' * 70}")
            print(f"Testing: meiki_fork[{lang_code}] + preprocessing={config_name}")
            print("=" * 70)

            preprocess_desc = []
            if config.get("target_width"):
                preprocess_desc.append(f"resize to {config['target_width']}px")
            if config.get("blur_size", 0) > 0:
                preprocess_desc.append(f"blur {config['blur_size']}x{config['blur_size']}")
            print(f"Preprocessing: {' + '.join(preprocess_desc) if preprocess_desc else 'none (raw images)'}")

            try:
                metrics = run_single_test_with_config(ocr, dataset_path, ground_truth, config)

                if metrics:
                    result = {
                        "approach": "meiki_multilingual_fork",
                        "language": lang_code,
                        "language_name": lang_name,
                        "preprocessing": config_name,
                        **{k: v for k, v in metrics.items() if k != "results"},
                    }
                    all_results["models"].append(result)
                    print(f"=> Avg: {metrics['avg_time_ms']:.0f}ms, {metrics['avg_similarity']:.1%} similarity, {metrics['avg_word_accuracy']:.1%} word acc")

            except Exception as e:
                print(f"Failed: {e}")
                import traceback
                traceback.print_exc()

    # Summary
    print("\n" + "=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)
    print(f"{'Model':<45} {'Time':<10} {'Similarity':<12} {'Word Acc':<10}")
    print("-" * 80)

    for r in sorted(all_results["models"], key=lambda x: x["avg_similarity"], reverse=True):
        label = f"meiki_fork[{r['language']}]+{r['preprocessing']}"
        print(f"{label:<45} {r['avg_time_ms']:<10.0f} {r['avg_similarity']:<12.1%} {r['avg_word_accuracy']:<10.1%}")

    if all_results["models"]:
        best = max(all_results["models"], key=lambda x: x["avg_similarity"])
        print(f"\n>>> Best: meiki_fork[{best['language']}]+{best['preprocessing']} ({best['avg_similarity']:.1%})")

    # Save results
    output_path = benchmark_dir / "meiki_hybrid_results.json"
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nSaved to: {output_path}")


if __name__ == "__main__":
    main()
