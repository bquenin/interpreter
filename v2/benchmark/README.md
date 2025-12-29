# OCR Benchmark

This folder contains test data and scripts for benchmarking OCR accuracy on Japanese game text.

## Structure

```
benchmark/
├── data/                    # Test cases
│   ├── 001_miguel_pendant/
│   │   ├── textbox.png      # Cropped textbox image (required)
│   │   ├── screenshot.png   # Full game screenshot (optional, for future textbox detection)
│   │   ├── ground_truth.txt # Expected OCR output (required)
│   │   └── textbox_coords.json  # Textbox location in screenshot (optional)
│   └── ...
├── results/                 # Benchmark results (JSON)
├── run_benchmark.py         # Benchmark script
└── README.md
```

## Running Benchmarks

```bash
# Run full benchmark (all engines, all preprocessing)
python benchmark/run_benchmark.py

# Run specific engine
python benchmark/run_benchmark.py --engine meikiocr

# Run specific preprocessing
python benchmark/run_benchmark.py --preprocessing otsu

# Save results to JSON
python benchmark/run_benchmark.py --save
```

## Adding New Test Cases

1. Create a new folder in `benchmark/data/` with format `NNN_description/`:
   ```
   benchmark/data/003_my_test_case/
   ```

2. Add required files:
   - `textbox.png` - Cropped image of the textbox only
   - `ground_truth.txt` - Expected OCR output (exact text)

3. Optionally add:
   - `screenshot.png` - Full game screenshot
   - `textbox_coords.json` - Bounding box coordinates for textbox detection testing

4. Run benchmark to verify:
   ```bash
   python benchmark/run_benchmark.py --save
   ```

## OCR Engines

| Engine | Description |
|--------|-------------|
| `manga_ocr` | VisionEncoderDecoder model for manga text |
| `meikiocr` | ONNX model trained on Japanese video game text |

## Preprocessing Methods

| Method | Description |
|--------|-------------|
| `none` | No preprocessing, raw image |
| `otsu` | Otsu binarization only |
| `4x_lanczos` | 4x upscaling with LANCZOS interpolation |
| `4x_otsu` | 4x upscaling + Otsu binarization |
| `4x_otsu_invert` | 4x upscaling + Otsu + auto-invert |

## Results Format

Results are saved as JSON with this structure:

```json
{
  "timestamp": "2024-12-29T00:00:00",
  "engines": ["manga_ocr", "meikiocr"],
  "preprocessing": ["none", "otsu", ...],
  "test_cases": ["001_miguel_pendant", ...],
  "results": [
    {
      "test_case": "001_miguel_pendant",
      "engine": "meikiocr",
      "preprocessing": "otsu",
      "output": "...",
      "ground_truth": "...",
      "accuracy": 95.2
    }
  ]
}
```

## Current Best Configuration

Based on benchmarking: **MeikiOCR + Otsu** achieves ~86% average accuracy.

| Engine | Preprocessing | Average Accuracy |
|--------|---------------|------------------|
| MeikiOCR | Otsu | ~86% |
| MeikiOCR | None | ~80% |
| manga_ocr | 4x+Otsu+Invert | ~85% |
| manga_ocr | None | ~49% |
