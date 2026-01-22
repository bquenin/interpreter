#!/usr/bin/env python3
"""Benchmark spell-check post-processing on OCR output.

Tests pyspellchecker on OCR results to see if it improves accuracy.
"""

import json
import os
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from spellchecker import SpellChecker

# Best models from benchmark
DET_MODEL = "PP-OCRv3_mobile_det"
REC_MODEL = "en_PP-OCRv3_mobile_rec"

# Best preprocessing
TARGET_WIDTH = 700
BLUR_SIZE = 5


def load_ground_truth(dataset_path: Path) -> dict:
    gt_path = dataset_path / "ground_truth.json"
    with open(gt_path) as f:
        return json.load(f)


def load_image_as_array(image_path: Path) -> np.ndarray:
    img = Image.open(image_path).convert("RGB")
    ratio = TARGET_WIDTH / img.width
    new_height = int(img.height * ratio)
    img = img.resize((TARGET_WIDTH, new_height), Image.Resampling.LANCZOS)
    rgb_array = np.array(img)
    rgb_array = cv2.GaussianBlur(rgb_array, (BLUR_SIZE, BLUR_SIZE), 0)
    return rgb_array


def levenshtein(s1: str, s2: str) -> int:
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


def calculate_similarity(text1: str, text2: str) -> float:
    t1 = text1.lower().strip()
    t2 = text2.lower().strip()
    edit_dist = levenshtein(t1, t2)
    max_len = max(len(t1), len(t2), 1)
    return 1 - (edit_dist / max_len)


def extract_text_from_result(ocr_result) -> str:
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


def spellcheck_text(text: str, spell: SpellChecker, skip_capitalized: bool = False) -> tuple[str, list]:
    """Apply spell checking to text. Returns corrected text and list of changes."""
    words = text.split()
    corrected_words = []
    changes = []

    for word in words:
        # Preserve punctuation
        prefix = ""
        suffix = ""
        clean_word = word

        # Strip leading punctuation
        while clean_word and not clean_word[0].isalnum():
            prefix += clean_word[0]
            clean_word = clean_word[1:]

        # Strip trailing punctuation
        while clean_word and not clean_word[-1].isalnum():
            suffix = clean_word[-1] + suffix
            clean_word = clean_word[:-1]

        if not clean_word:
            corrected_words.append(word)
            continue

        # Skip capitalized words (likely proper nouns)
        if skip_capitalized and clean_word[0].isupper():
            corrected_words.append(word)
            continue

        # Check if word is misspelled
        if clean_word.lower() in spell:
            # Word is correct
            corrected_words.append(word)
        else:
            # Get correction
            correction = spell.correction(clean_word.lower())
            if correction and correction != clean_word.lower():
                # Preserve original case pattern
                if clean_word.isupper():
                    correction = correction.upper()
                elif clean_word[0].isupper():
                    correction = correction.capitalize()

                changes.append((clean_word, correction))
                corrected_words.append(prefix + correction + suffix)
            else:
                # No good correction found, keep original
                corrected_words.append(word)

    return " ".join(corrected_words), changes


def main():
    os.environ["DISABLE_MODEL_SOURCE_CHECK"] = "True"

    from paddleocr import PaddleOCR

    benchmark_dir = Path(__file__).parent
    dataset_path = benchmark_dir / "dataset"

    print("Post-Processing Benchmark (pyspellchecker)")
    print("=" * 70)

    ground_truth = load_ground_truth(dataset_path)
    print(f"Images: {len(ground_truth)}")

    # Initialize OCR
    print("\nInitializing OCR...")
    ocr = PaddleOCR(
        text_detection_model_name=DET_MODEL,
        text_recognition_model_name=REC_MODEL,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )

    # Initialize spell checker
    spell = SpellChecker()

    # Run OCR and compare with/without spell check
    results_raw = []
    results_corrected = []
    all_changes = []

    print(f"\n{'Image':<20} {'Raw':<8} {'Corrected':<10} {'Changes'}")
    print("-" * 70)

    for filename, gt_data in ground_truth.items():
        image_path = dataset_path / filename
        if not image_path.exists():
            continue

        img_array = load_image_as_array(image_path)
        ocr_result = ocr.predict(img_array)
        ocr_text = extract_text_from_result(ocr_result)
        gt_text = gt_data["text"]

        # Raw similarity
        raw_sim = calculate_similarity(ocr_text, gt_text)

        # Corrected similarity (skip capitalized words to preserve proper nouns)
        corrected_text, changes = spellcheck_text(ocr_text, spell, skip_capitalized=True)
        corrected_sim = calculate_similarity(corrected_text, gt_text)

        results_raw.append(raw_sim)
        results_corrected.append(corrected_sim)

        # Track changes
        change_str = ", ".join([f"{old}→{new}" for old, new in changes]) if changes else "-"
        all_changes.extend(changes)

        diff = corrected_sim - raw_sim
        diff_str = f"+{diff:.1%}" if diff > 0 else f"{diff:.1%}" if diff < 0 else "="

        print(f"{filename:<20} {raw_sim:<8.1%} {corrected_sim:<10.1%} {change_str[:40]}")

    # Summary
    avg_raw = sum(results_raw) / len(results_raw)
    avg_corrected = sum(results_corrected) / len(results_corrected)
    improvement = avg_corrected - avg_raw

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Average raw:       {avg_raw:.1%}")
    print(f"Average corrected: {avg_corrected:.1%}")
    print(f"Improvement:       {improvement:+.1%}")
    print(f"Total corrections: {len(all_changes)}")

    # Show all unique corrections
    if all_changes:
        print("\nAll corrections made:")
        unique_changes = {}
        for old, new in all_changes:
            key = f"{old}→{new}"
            unique_changes[key] = unique_changes.get(key, 0) + 1

        for change, count in sorted(unique_changes.items(), key=lambda x: -x[1]):
            print(f"  {change} ({count}x)")


if __name__ == "__main__":
    main()
