#!/usr/bin/env python3
"""OCR Benchmark Script for Interpreter v2.

This script runs comprehensive OCR benchmarks across multiple test cases,
OCR engines, and preprocessing configurations. Results are saved as JSON
for historical comparison.

Usage:
    python benchmark/run_benchmark.py
    python benchmark/run_benchmark.py --engine meikiocr  # Single engine
    python benchmark/run_benchmark.py --save             # Save results to JSON
    python benchmark/run_benchmark.py --translate        # Include translation
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
# Translation Engine
# ============================================================================

class SugoiTranslator:
    """Wrapper for Sugoi V4 translation model."""

    def __init__(self):
        self.translator = None
        self.tokenizer = None
        self.model_path = PROJECT_ROOT / "models" / "sugoi-v4-ja-en-ct2"

    def load(self):
        if self.translator is None:
            print("  Loading Sugoi V4 translator...")
            import ctranslate2
            import sentencepiece as spm

            self.translator = ctranslate2.Translator(
                str(self.model_path),
                device="auto"
            )
            self.tokenizer = spm.SentencePieceProcessor()
            self.tokenizer.Load(str(self.model_path / "spm" / "spm.ja.nopretok.model"))

    def translate(self, text: str) -> str:
        """Translate Japanese text to English."""
        if not text.strip():
            return ""

        # Tokenize
        tokens = self.tokenizer.EncodeAsPieces(text)

        # Translate
        results = self.translator.translate_batch(
            [tokens],
            beam_size=5,
            max_decoding_length=256
        )

        # Decode - join tokens and clean up SentencePiece artifacts
        translated_tokens = results[0].hypotheses[0]
        result = "".join(translated_tokens).replace("▁", " ").strip()
        return result


class DeepLTranslator:
    """Wrapper for DeepL API translation."""

    def __init__(self):
        self.translator = None

    def load(self):
        if self.translator is None:
            print("  Loading DeepL translator...")
            import deepl
            api_key = os.environ.get("DEEPL_API_KEY")
            if not api_key:
                raise ValueError("DEEPL_API_KEY environment variable not set")
            self.translator = deepl.Translator(api_key)

    def translate(self, text: str) -> str:
        """Translate Japanese text to English."""
        if not text.strip():
            return ""
        import time
        time.sleep(0.5)  # Rate limit protection
        for attempt in range(3):
            try:
                result = self.translator.translate_text(text, source_lang="JA", target_lang="EN-US")
                return result.text
            except Exception as e:
                if attempt < 2:
                    time.sleep(2)  # Wait longer before retry
                else:
                    print(f"    [DeepL error: {e}]")
                    return f"[ERROR: {e}]"


TRANSLATORS = {
    "sugoi": SugoiTranslator,
    "deepl": DeepLTranslator,
}


# ============================================================================
# Test Case Discovery
# ============================================================================

def discover_test_cases() -> list[dict]:
    """Discover all test cases from benchmark/data/ folder.

    Returns:
        List of test case dicts with keys: id, name, image_path, ground_truth,
        ground_truth_translation (optional)
    """
    data_dir = BENCHMARK_DIR / "data"
    test_cases = []

    for case_dir in sorted(data_dir.iterdir()):
        if not case_dir.is_dir():
            continue

        # Prefer content.png (cropped), fall back to screenshot.png
        content_path = case_dir / "content.png"
        screenshot_path = case_dir / "screenshot.png"
        ground_truth_path = case_dir / "ground_truth.txt"
        ground_truth_translation_path = case_dir / "ground_truth_translation.txt"

        if content_path.exists():
            image_path = content_path
        elif screenshot_path.exists():
            image_path = screenshot_path
        else:
            print(f"Warning: {case_dir.name} missing content.png/screenshot.png, skipping")
            continue

        if not ground_truth_path.exists():
            print(f"Warning: {case_dir.name} missing ground_truth.txt, skipping")
            continue

        ground_truth = ground_truth_path.read_text().strip()

        # Ground truth translations are optional (one per line for alternatives)
        ground_truth_translations = []
        if ground_truth_translation_path.exists():
            lines = ground_truth_translation_path.read_text().strip().split("\n")
            ground_truth_translations = [line.strip() for line in lines if line.strip()]

        test_cases.append({
            "id": case_dir.name.split("_")[0],
            "name": case_dir.name,
            "image_path": str(image_path),
            "ground_truth": ground_truth,
            "ground_truth_translations": ground_truth_translations,
        })

    return test_cases


# ============================================================================
# Main Benchmark Runner
# ============================================================================

def run_benchmark(
    engines: list[str] | None = None,
    preprocessing: list[str] | None = None,
    save_results: bool = False,
    include_translation: bool = False,
    translator_names: list[str] | None = None,
) -> dict:
    """Run the OCR benchmark.

    Args:
        engines: List of engine names to test (default: all)
        preprocessing: List of preprocessing methods to test (default: all)
        save_results: Whether to save results to JSON file
        include_translation: Whether to include translation in the benchmark
        translator_names: Which translators to use (default: all)

    Returns:
        Results dictionary
    """
    # Defaults
    if engines is None:
        engines = list(OCR_ENGINES.keys())
    if preprocessing is None:
        preprocessing = list(PREPROCESSING_METHODS.keys())
    if translator_names is None:
        translator_names = list(TRANSLATORS.keys())

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

    # Load translators if needed
    loaded_translators = {}
    if include_translation:
        print("\nLoading translators...")
        for tl_name in translator_names:
            if tl_name not in TRANSLATORS:
                print(f"Warning: Unknown translator '{tl_name}', skipping")
                continue
            translator = TRANSLATORS[tl_name]()
            translator.load()
            loaded_translators[tl_name] = translator

    # Run benchmark
    print("\n" + "=" * 80)
    print("RUNNING BENCHMARK")
    print("=" * 80)

    results = {
        "timestamp": datetime.now().isoformat(),
        "engines": engines,
        "preprocessing": preprocessing,
        "include_translation": include_translation,
        "test_cases": [tc["name"] for tc in test_cases],
        "results": [],
    }

    for test_case in test_cases:
        print(f"\n--- {test_case['name']} ---")
        print(f"Ground truth OCR: {test_case['ground_truth']}")
        if include_translation and test_case.get("ground_truth_translations"):
            print(f"Ground truth TL:  {test_case['ground_truth_translations'][0]}")
            if len(test_case['ground_truth_translations']) > 1:
                print(f"                  (+{len(test_case['ground_truth_translations']) - 1} alternatives)")

        image = Image.open(test_case["image_path"])

        for preproc_name in preprocessing:
            if preproc_name not in PREPROCESSING_METHODS:
                continue

            preproc_func = PREPROCESSING_METHODS[preproc_name]
            processed = preproc_func(image)

            for engine_name, engine in loaded_engines.items():
                output = engine.run(processed)
                ocr_accuracy = calculate_accuracy(output, test_case["ground_truth"])

                result = {
                    "test_case": test_case["name"],
                    "engine": engine_name,
                    "preprocessing": preproc_name,
                    "ocr_output": output,
                    "ground_truth": test_case["ground_truth"],
                    "ocr_accuracy": round(ocr_accuracy, 2),
                    "translations": {},
                }

                # Add translations if enabled
                if include_translation:
                    for tl_name, translator in loaded_translators.items():
                        translation = translator.translate(output) if output.strip() else ""
                        tl_result = {"output": translation}
                        if test_case.get("ground_truth_translations"):
                            # Compare against all valid translations, use best match
                            best_tl_accuracy = 0.0
                            best_match = test_case["ground_truth_translations"][0]
                            for gt_tl in test_case["ground_truth_translations"]:
                                acc = calculate_accuracy(translation, gt_tl)
                                if acc > best_tl_accuracy:
                                    best_tl_accuracy = acc
                                    best_match = gt_tl
                            tl_result["accuracy"] = round(best_tl_accuracy, 2)
                            tl_result["best_match"] = best_match
                        result["translations"][tl_name] = tl_result

                results["results"].append(result)

                # Print results
                if include_translation:
                    tl_strs = []
                    for tl_name in loaded_translators:
                        if tl_name in result["translations"] and "accuracy" in result["translations"][tl_name]:
                            tl_strs.append(f"{tl_name}={result['translations'][tl_name]['accuracy']:.1f}%")
                    tl_summary = " | ".join(tl_strs) if tl_strs else "N/A"
                    print(f"  {engine_name} + {preproc_name}: OCR {ocr_accuracy:.1f}% | TL: {tl_summary}")
                    if len(output) > 50:
                        print(f"    OCR: {output[:50]}...")
                    else:
                        print(f"    OCR: {output}")
                else:
                    print(f"  {engine_name} + {preproc_name}: {ocr_accuracy:.1f}%")
                    print(f"    Output: {output[:50]}..." if len(output) > 50 else f"    Output: {output}")

    # Print summary table
    print("\n" + "=" * 80)
    print("SUMMARY TABLE - OCR Accuracy")
    print("=" * 80)

    # Group results by engine + preprocessing
    ocr_summary = {}
    tl_summaries = {tl_name: {} for tl_name in loaded_translators}
    for r in results["results"]:
        key = (r["engine"], r["preprocessing"])
        if key not in ocr_summary:
            ocr_summary[key] = []
        ocr_summary[key].append(r["ocr_accuracy"])

        # Group translation results by translator
        for tl_name in loaded_translators:
            if key not in tl_summaries[tl_name]:
                tl_summaries[tl_name][key] = []
            if tl_name in r.get("translations", {}) and "accuracy" in r["translations"][tl_name]:
                tl_summaries[tl_name][key].append(r["translations"][tl_name]["accuracy"])

    # Print OCR header
    header = f"{'Engine':<12} {'Preprocessing':<18}"
    for tc in test_cases:
        header += f" {tc['id']:<8}"
    header += f" {'Avg':<8}"
    print(header)
    print("-" * len(header))

    # Print OCR rows
    for engine_name in engines:
        for preproc_name in preprocessing:
            key = (engine_name, preproc_name)
            if key not in ocr_summary:
                continue
            accuracies = ocr_summary[key]
            avg = sum(accuracies) / len(accuracies)

            row = f"{engine_name:<12} {preproc_name:<18}"
            for acc in accuracies:
                row += f" {acc:>6.1f}%"
            row += f" {avg:>6.1f}%"
            print(row)

    # Print translation summary for each translator
    for tl_name, tl_summary in tl_summaries.items():
        if not any(tl_summary.values()):
            continue
        print("\n" + "=" * 80)
        print(f"SUMMARY TABLE - Translation Accuracy ({tl_name})")
        print("=" * 80)
        print(header)
        print("-" * len(header))

        for engine_name in engines:
            for preproc_name in preprocessing:
                key = (engine_name, preproc_name)
                if key not in tl_summary or not tl_summary[key]:
                    continue
                accuracies = tl_summary[key]
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

    best_ocr_avg = max(ocr_summary.items(), key=lambda x: sum(x[1]) / len(x[1]))
    avg_ocr_acc = sum(best_ocr_avg[1]) / len(best_ocr_avg[1])
    print(f"Best OCR average: {best_ocr_avg[0][0]} + {best_ocr_avg[0][1]} = {avg_ocr_acc:.1f}%")

    best_ocr_single = max(results["results"], key=lambda x: x["ocr_accuracy"])
    print(f"Best OCR single:  {best_ocr_single['engine']} + {best_ocr_single['preprocessing']} "
          f"on {best_ocr_single['test_case']} = {best_ocr_single['ocr_accuracy']:.1f}%")

    # Best translation for each translator
    for tl_name, tl_summary in tl_summaries.items():
        if not any(tl_summary.values()):
            continue
        best_tl_avg = max(
            [(k, v) for k, v in tl_summary.items() if v],
            key=lambda x: sum(x[1]) / len(x[1])
        )
        avg_tl_acc = sum(best_tl_avg[1]) / len(best_tl_avg[1])
        print(f"Best TL avg ({tl_name}): {best_tl_avg[0][0]} + {best_tl_avg[0][1]} = {avg_tl_acc:.1f}%")

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
    parser.add_argument(
        "--translate", "-t",
        action="store_true",
        help="Include translation in benchmark"
    )
    parser.add_argument(
        "--translator",
        type=str,
        action="append",
        choices=list(TRANSLATORS.keys()),
        help="Translator(s) to use (default: all). Can be specified multiple times."
    )

    args = parser.parse_args()

    run_benchmark(
        engines=args.engine,
        preprocessing=args.preprocessing,
        save_results=args.save,
        include_translation=args.translate,
        translator_names=args.translator,
    )


if __name__ == "__main__":
    main()
