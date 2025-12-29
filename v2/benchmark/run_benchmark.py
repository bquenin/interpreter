#!/usr/bin/env python3
"""OCR Benchmark Script for Interpreter v2.

This script runs comprehensive OCR benchmarks across multiple test cases,
OCR engines, and preprocessing configurations. Results are saved as JSON
for historical comparison.

Usage:
    python benchmark/run_benchmark.py
    python benchmark/run_benchmark.py --engine meikiocr  # Single engine
    python benchmark/run_benchmark.py --save             # Save results to JSON
"""

import argparse
import json
import os
import sys
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

# Add parent directory to path for imports
BENCHMARK_DIR = Path(__file__).parent
PROJECT_ROOT = BENCHMARK_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))


def calculate_accuracy(output: str, expected: str) -> float:
    """Calculate character-level accuracy using SequenceMatcher.

    Args:
        output: OCR output text
        expected: Ground truth text

    Returns:
        Accuracy as percentage (0-100)
    """
    if not expected:
        return 0.0
    matcher = SequenceMatcher(None, output, expected)
    return matcher.ratio() * 100


# ============================================================================
# Preprocessing Functions
# ============================================================================

def preprocess_none(image: Image.Image) -> np.ndarray:
    """No preprocessing - just convert to numpy RGB."""
    return np.array(image.convert('RGB'))


def preprocess_otsu(image: Image.Image) -> np.ndarray:
    """Otsu binarization only (no upscaling)."""
    img_array = np.array(image)
    if len(img_array.shape) == 3:
        gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
    else:
        gray = img_array
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return cv2.cvtColor(binary, cv2.COLOR_GRAY2RGB)


def preprocess_4x_lanczos(image: Image.Image) -> np.ndarray:
    """4x upscaling with LANCZOS interpolation."""
    img_array = np.array(image.convert('RGB'))
    h, w = img_array.shape[:2]
    upscaled = cv2.resize(img_array, (w * 4, h * 4), interpolation=cv2.INTER_LANCZOS4)
    return upscaled


def preprocess_4x_otsu(image: Image.Image) -> np.ndarray:
    """4x upscaling + Otsu binarization."""
    img_array = np.array(image)
    if len(img_array.shape) == 3:
        gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
    else:
        gray = img_array
    upscaled = cv2.resize(gray, (gray.shape[1] * 4, gray.shape[0] * 4),
                          interpolation=cv2.INTER_LANCZOS4)
    _, binary = cv2.threshold(upscaled, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return cv2.cvtColor(binary, cv2.COLOR_GRAY2RGB)


def preprocess_4x_otsu_invert(image: Image.Image) -> np.ndarray:
    """4x upscaling + Otsu binarization + auto-invert if needed."""
    img_array = np.array(image)
    if len(img_array.shape) == 3:
        gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
    else:
        gray = img_array
    upscaled = cv2.resize(gray, (gray.shape[1] * 4, gray.shape[0] * 4),
                          interpolation=cv2.INTER_LANCZOS4)
    _, binary = cv2.threshold(upscaled, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    white_ratio = np.mean(binary > 127)
    if white_ratio < 0.5:
        binary = 255 - binary
    return cv2.cvtColor(binary, cv2.COLOR_GRAY2RGB)


PREPROCESSING_METHODS = {
    "none": preprocess_none,
    "otsu": preprocess_otsu,
    "4x_lanczos": preprocess_4x_lanczos,
    "4x_otsu": preprocess_4x_otsu,
    "4x_otsu_invert": preprocess_4x_otsu_invert,
}


# ============================================================================
# OCR Engine Wrappers
# ============================================================================

class MangaOCREngine:
    """Wrapper for manga-ocr."""

    def __init__(self):
        self.model = None

    def load(self):
        if self.model is None:
            print("  Loading manga-ocr...")
            from manga_ocr import MangaOcr
            self.model = MangaOcr()

    def run(self, img_array: np.ndarray) -> str:
        pil_image = Image.fromarray(img_array)
        return self.model(pil_image)


class MeikiOCREngine:
    """Wrapper for MeikiOCR."""

    def __init__(self):
        self.model = None

    def load(self):
        if self.model is None:
            print("  Loading MeikiOCR...")
            from meikiocr import MeikiOCR
            self.model = MeikiOCR()

    def run(self, img_array: np.ndarray) -> str:
        results = self.model.run_ocr(img_array)
        texts = [r['text'] for r in results if 'text' in r]
        return ''.join(texts)


OCR_ENGINES = {
    "manga_ocr": MangaOCREngine,
    "meikiocr": MeikiOCREngine,
}


# ============================================================================
# Test Case Discovery
# ============================================================================

def discover_test_cases() -> list[dict]:
    """Discover all test cases from benchmark/data/ folder.

    Returns:
        List of test case dicts with keys: id, name, textbox_path, ground_truth
    """
    data_dir = BENCHMARK_DIR / "data"
    test_cases = []

    for case_dir in sorted(data_dir.iterdir()):
        if not case_dir.is_dir():
            continue

        textbox_path = case_dir / "textbox.png"
        ground_truth_path = case_dir / "ground_truth.txt"

        if not textbox_path.exists():
            print(f"Warning: {case_dir.name} missing textbox.png, skipping")
            continue
        if not ground_truth_path.exists():
            print(f"Warning: {case_dir.name} missing ground_truth.txt, skipping")
            continue

        ground_truth = ground_truth_path.read_text().strip()

        test_cases.append({
            "id": case_dir.name.split("_")[0],
            "name": case_dir.name,
            "textbox_path": str(textbox_path),
            "ground_truth": ground_truth,
        })

    return test_cases


# ============================================================================
# Main Benchmark Runner
# ============================================================================

def run_benchmark(
    engines: list[str] | None = None,
    preprocessing: list[str] | None = None,
    save_results: bool = False,
) -> dict:
    """Run the OCR benchmark.

    Args:
        engines: List of engine names to test (default: all)
        preprocessing: List of preprocessing methods to test (default: all)
        save_results: Whether to save results to JSON file

    Returns:
        Results dictionary
    """
    # Defaults
    if engines is None:
        engines = list(OCR_ENGINES.keys())
    if preprocessing is None:
        preprocessing = list(PREPROCESSING_METHODS.keys())

    # Discover test cases
    print("Discovering test cases...")
    test_cases = discover_test_cases()
    if not test_cases:
        print("Error: No test cases found in benchmark/data/")
        return {}
    print(f"Found {len(test_cases)} test cases")

    # Load OCR engines
    print("\nLoading OCR engines...")
    loaded_engines = {}
    for engine_name in engines:
        if engine_name not in OCR_ENGINES:
            print(f"Warning: Unknown engine '{engine_name}', skipping")
            continue
        engine = OCR_ENGINES[engine_name]()
        engine.load()
        loaded_engines[engine_name] = engine

    # Run benchmark
    print("\n" + "=" * 80)
    print("RUNNING BENCHMARK")
    print("=" * 80)

    results = {
        "timestamp": datetime.now().isoformat(),
        "engines": engines,
        "preprocessing": preprocessing,
        "test_cases": [tc["name"] for tc in test_cases],
        "results": [],
    }

    for test_case in test_cases:
        print(f"\n--- {test_case['name']} ---")
        print(f"Ground truth: {test_case['ground_truth']}")

        image = Image.open(test_case["textbox_path"])

        for preproc_name in preprocessing:
            if preproc_name not in PREPROCESSING_METHODS:
                continue

            preproc_func = PREPROCESSING_METHODS[preproc_name]
            processed = preproc_func(image)

            for engine_name, engine in loaded_engines.items():
                output = engine.run(processed)
                accuracy = calculate_accuracy(output, test_case["ground_truth"])

                result = {
                    "test_case": test_case["name"],
                    "engine": engine_name,
                    "preprocessing": preproc_name,
                    "output": output,
                    "ground_truth": test_case["ground_truth"],
                    "accuracy": round(accuracy, 2),
                }
                results["results"].append(result)

                print(f"  {engine_name} + {preproc_name}: {accuracy:.1f}%")
                print(f"    Output: {output[:50]}..." if len(output) > 50 else f"    Output: {output}")

    # Print summary table
    print("\n" + "=" * 80)
    print("SUMMARY TABLE")
    print("=" * 80)

    # Group results by engine + preprocessing
    summary = {}
    for r in results["results"]:
        key = (r["engine"], r["preprocessing"])
        if key not in summary:
            summary[key] = []
        summary[key].append(r["accuracy"])

    # Print header
    header = f"{'Engine':<12} {'Preprocessing':<18}"
    for tc in test_cases:
        header += f" {tc['id']:<8}"
    header += f" {'Avg':<8}"
    print(header)
    print("-" * len(header))

    # Print rows
    for engine_name in engines:
        for preproc_name in preprocessing:
            key = (engine_name, preproc_name)
            if key not in summary:
                continue
            accuracies = summary[key]
            avg = sum(accuracies) / len(accuracies)

            row = f"{engine_name:<12} {preproc_name:<18}"
            for acc in accuracies:
                row += f" {acc:>6.1f}%"
            row += f" {avg:>6.1f}%"
            print(row)

    # Find best configuration
    print("\n" + "=" * 80)
    print("BEST RESULTS")
    print("=" * 80)

    best_avg = max(summary.items(), key=lambda x: sum(x[1]) / len(x[1]))
    avg_acc = sum(best_avg[1]) / len(best_avg[1])
    print(f"Best average: {best_avg[0][0]} + {best_avg[0][1]} = {avg_acc:.1f}%")

    best_single = max(results["results"], key=lambda x: x["accuracy"])
    print(f"Best single:  {best_single['engine']} + {best_single['preprocessing']} "
          f"on {best_single['test_case']} = {best_single['accuracy']:.1f}%")

    # Save results if requested
    if save_results:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        results_path = BENCHMARK_DIR / "results" / f"{timestamp}.json"
        results_path.parent.mkdir(exist_ok=True)

        with open(results_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\nResults saved to: {results_path}")

    return results


def main():
    parser = argparse.ArgumentParser(description="Run OCR benchmark")
    parser.add_argument(
        "--engine", "-e",
        type=str,
        action="append",
        choices=list(OCR_ENGINES.keys()),
        help="OCR engine(s) to test (default: all)"
    )
    parser.add_argument(
        "--preprocessing", "-p",
        type=str,
        action="append",
        choices=list(PREPROCESSING_METHODS.keys()),
        help="Preprocessing method(s) to test (default: all)"
    )
    parser.add_argument(
        "--save", "-s",
        action="store_true",
        help="Save results to JSON file"
    )

    args = parser.parse_args()

    run_benchmark(
        engines=args.engine,
        preprocessing=args.preprocessing,
        save_results=args.save,
    )


if __name__ == "__main__":
    main()
