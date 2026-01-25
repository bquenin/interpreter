#!/usr/bin/env python3
"""Benchmark different preprocessing approaches for pixel fonts.

Compares:
1. Raw (no preprocessing)
2. Simple LANCZOS resize to 700px
3. Interpreter approach: downscale to 300px + 4x NEAREST upscale = 1200px
"""

import json
import os
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

# Best models from previous benchmark
DET_MODEL = "PP-OCRv3_mobile_det"
REC_MODEL = "en_PP-OCRv3_mobile_rec"


def load_ground_truth(dataset_path: Path) -> dict:
    """Load ground truth data from JSON file."""
    gt_path = dataset_path / "ground_truth.json"
    with open(gt_path) as f:
        return json.load(f)


def preprocess_raw(image_path: Path) -> np.ndarray:
    """No preprocessing - raw image."""
    img = Image.open(image_path).convert("RGB")
    return np.array(img)


def preprocess_lanczos(image_path: Path, target_width: int = 700) -> np.ndarray:
    """Simple LANCZOS resize to target width."""
    img = Image.open(image_path).convert("RGB")
    if img.width != target_width:
        ratio = target_width / img.width
        new_height = int(img.height * ratio)
        img = img.resize((target_width, new_height), Image.Resampling.LANCZOS)
    return np.array(img)


def preprocess_interpreter(
    image_path: Path,
    downscale_dim: int = 300,
    upscale_factor: int = 4,
) -> np.ndarray:
    """Interpreter approach: downscale + NEAREST upscale."""
    img = Image.open(image_path).convert("RGB")
    rgb_array = np.array(img)
    h, w = rgb_array.shape[:2]

    # Step 1: Downscale if image is larger than target
    if max(h, w) > downscale_dim:
        scale = downscale_dim / max(h, w)
        new_w = int(w * scale)
        new_h = int(h * scale)
        rgb_array = cv2.resize(rgb_array, (new_w, new_h), interpolation=cv2.INTER_AREA)

    # Step 2: Upscale with NEAREST neighbor
    h, w = rgb_array.shape[:2]
    upscale_w = w * upscale_factor
    upscale_h = h * upscale_factor
    rgb_array = cv2.resize(rgb_array, (upscale_w, upscale_h), interpolation=cv2.INTER_NEAREST)

    return rgb_array


def preprocess_lanczos_blur(
    image_path: Path,
    target_width: int = 700,
    blur_size: int = 3,
) -> np.ndarray:
    """LANCZOS resize + Gaussian blur to smooth pixel edges."""
    img = Image.open(image_path).convert("RGB")
    if img.width != target_width:
        ratio = target_width / img.width
        new_height = int(img.height * ratio)
        img = img.resize((target_width, new_height), Image.Resampling.LANCZOS)

    rgb_array = np.array(img)

    # Apply slight Gaussian blur to smooth pixel edges
    rgb_array = cv2.GaussianBlur(rgb_array, (blur_size, blur_size), 0)

    return rgb_array


def preprocess_lanczos_sharpen(
    image_path: Path,
    target_width: int = 700,
) -> np.ndarray:
    """LANCZOS resize + unsharp mask sharpening."""
    img = Image.open(image_path).convert("RGB")
    if img.width != target_width:
        ratio = target_width / img.width
        new_height = int(img.height * ratio)
        img = img.resize((target_width, new_height), Image.Resampling.LANCZOS)

    rgb_array = np.array(img)

    # Unsharp mask: original + (original - blurred) * amount
    blurred = cv2.GaussianBlur(rgb_array, (5, 5), 0)
    rgb_array = cv2.addWeighted(rgb_array, 1.5, blurred, -0.5, 0)

    return rgb_array


def preprocess_bilinear(
    image_path: Path,
    target_width: int = 700,
) -> np.ndarray:
    """Bilinear resize (smoother than LANCZOS for pixel art)."""
    img = Image.open(image_path).convert("RGB")
    if img.width != target_width:
        ratio = target_width / img.width
        new_height = int(img.height * ratio)
        img = img.resize((target_width, new_height), Image.Resampling.BILINEAR)

    return np.array(img)


def preprocess_bicubic(
    image_path: Path,
    target_width: int = 700,
) -> np.ndarray:
    """Bicubic resize."""
    img = Image.open(image_path).convert("RGB")
    if img.width != target_width:
        ratio = target_width / img.width
        new_height = int(img.height * ratio)
        img = img.resize((target_width, new_height), Image.Resampling.BICUBIC)

    return np.array(img)


def preprocess_grayscale(
    image_path: Path,
    target_width: int = 700,
) -> np.ndarray:
    """LANCZOS resize + convert to grayscale (as 3-channel for OCR)."""
    img = Image.open(image_path).convert("RGB")
    if img.width != target_width:
        ratio = target_width / img.width
        new_height = int(img.height * ratio)
        img = img.resize((target_width, new_height), Image.Resampling.LANCZOS)

    # Convert to grayscale
    gray = img.convert("L")
    # Convert back to 3-channel (OCR expects RGB)
    return np.array(gray.convert("RGB"))


def preprocess_invert(
    image_path: Path,
    target_width: int = 700,
) -> np.ndarray:
    """LANCZOS resize + invert colors (white text on dark → black text on light)."""
    img = Image.open(image_path).convert("RGB")
    if img.width != target_width:
        ratio = target_width / img.width
        new_height = int(img.height * ratio)
        img = img.resize((target_width, new_height), Image.Resampling.LANCZOS)

    rgb_array = np.array(img)
    # Invert colors
    rgb_array = 255 - rgb_array

    return rgb_array


def preprocess_bilateral(
    image_path: Path,
    target_width: int = 700,
) -> np.ndarray:
    """LANCZOS resize + bilateral filter (edge-preserving blur)."""
    img = Image.open(image_path).convert("RGB")
    if img.width != target_width:
        ratio = target_width / img.width
        new_height = int(img.height * ratio)
        img = img.resize((target_width, new_height), Image.Resampling.LANCZOS)

    rgb_array = np.array(img)
    # Bilateral filter: d=9, sigmaColor=75, sigmaSpace=75
    rgb_array = cv2.bilateralFilter(rgb_array, 9, 75, 75)

    return rgb_array


def preprocess_best_plus_grayscale(
    image_path: Path,
    target_width: int = 700,
) -> np.ndarray:
    """Best so far (LANCZOS + blur) + grayscale."""
    img = Image.open(image_path).convert("RGB")
    if img.width != target_width:
        ratio = target_width / img.width
        new_height = int(img.height * ratio)
        img = img.resize((target_width, new_height), Image.Resampling.LANCZOS)

    rgb_array = np.array(img)
    # Gaussian blur
    rgb_array = cv2.GaussianBlur(rgb_array, (5, 5), 0)
    # Convert to grayscale and back to 3-channel
    gray = cv2.cvtColor(rgb_array, cv2.COLOR_RGB2GRAY)
    rgb_array = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)

    return rgb_array


def levenshtein(s1: str, s2: str) -> int:
    """Calculate Levenshtein edit distance."""
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


def test_preprocessing(ocr, dataset_path: Path, ground_truth: dict, preprocess_fn, name: str) -> dict:
    """Test OCR with a specific preprocessing function."""
    results = []
    total_time = 0

    for filename, gt_data in ground_truth.items():
        image_path = dataset_path / filename
        if not image_path.exists():
            continue

        # Preprocess
        img_array = preprocess_fn(image_path)
        img_size = f"{img_array.shape[1]}x{img_array.shape[0]}"

        # OCR
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
            "img_size": img_size,
        })

    avg_time = total_time / len(results) * 1000
    avg_similarity = sum(r["similarity"] for r in results) / len(results)
    sample_size = results[0]["img_size"] if results else "N/A"

    return {
        "name": name,
        "avg_time_ms": avg_time,
        "avg_similarity": avg_similarity,
        "sample_size": sample_size,
        "results": results,
    }


def main():
    os.environ["DISABLE_MODEL_SOURCE_CHECK"] = "True"

    from paddleocr import PaddleOCR

    benchmark_dir = Path(__file__).parent
    dataset_path = benchmark_dir / "dataset"

    print("Preprocessing Approach Benchmark")
    print("=" * 70)
    print(f"Detection: {DET_MODEL}")
    print(f"Recognition: {REC_MODEL}")
    print("=" * 70)

    ground_truth = load_ground_truth(dataset_path)
    print(f"Images: {len(ground_truth)}")

    # Initialize OCR once
    print("\nInitializing OCR...")
    ocr = PaddleOCR(
        text_detection_model_name=DET_MODEL,
        text_recognition_model_name=REC_MODEL,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )

    # Define preprocessing approaches
    approaches = [
        ("LANCZOS 700 + blur 5x5 (best)", lambda p: preprocess_lanczos_blur(p, 700, 5)),
        ("BICUBIC 700px", lambda p: preprocess_bicubic(p, 700)),
        ("Grayscale", lambda p: preprocess_grayscale(p, 700)),
        ("Invert colors", lambda p: preprocess_invert(p, 700)),
        ("Bilateral filter", lambda p: preprocess_bilateral(p, 700)),
        ("Best + grayscale", lambda p: preprocess_best_plus_grayscale(p, 700)),
    ]

    # Test each approach
    all_results = []
    print(f"\n{'Approach':<30} {'Size':<15} {'Time (ms)':<12} {'Similarity':<12}")
    print("-" * 70)

    for name, preprocess_fn in approaches:
        result = test_preprocessing(ocr, dataset_path, ground_truth, preprocess_fn, name)
        all_results.append(result)
        print(f"{name:<30} {result['sample_size']:<15} {result['avg_time_ms']:<12.0f} {result['avg_similarity']:<12.1%}")

    # Find best
    best = max(all_results, key=lambda x: x["avg_similarity"])

    print("\n" + "=" * 70)
    print(f"Best: {best['name']} ({best['avg_similarity']:.1%}, {best['avg_time_ms']:.0f}ms)")

    # Save results
    output_path = benchmark_dir / "preprocess_results.json"
    summary = [{k: v for k, v in r.items() if k != "results"} for r in all_results]
    with open(output_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"Saved to: {output_path}")


if __name__ == "__main__":
    main()
