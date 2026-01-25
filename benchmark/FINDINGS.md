# OCR Benchmark Findings

Benchmark conducted on 26 screenshots from Tales of Phantasia (pixel font, white text on blue background).

## Best Configuration

| Setting | Value |
|---------|-------|
| Detection model | `PP-OCRv3_mobile_det` |
| Recognition model | `en_PP-OCRv3_mobile_rec` |
| Resize | LANCZOS to **700px** width (proportional) |
| Post-resize filter | Gaussian blur **5x5** |
| **Final accuracy** | **85.2%** |
| **Speed** | **~260ms per image** |

Improvement: 70.9% (raw) → 85.2% (optimized) = **+14.3%**

---

## 1. Model Selection

### Detection Models (Phase 1)
Fixed recognition: `en_PP-OCRv4_mobile_rec`

| Model | Time (ms) | Similarity |
|-------|-----------|------------|
| **v4_mobile** | 713 | **81.4%** |
| v4_server | 2081 | 80.8% |
| **v3_mobile** | **589** | **83.7%** |
| v3_server | 1675 | 83.2% |

**Winner: v3_mobile** - fastest and most accurate for pixel fonts.

**Key finding:** Mobile models outperform server models for pixel fonts. Server models failed completely on some images (0% detection on capture-08.png). Server models are trained on documents/photos, not pixel art.

### Recognition Models (Phase 2)
Fixed detection: `PP-OCRv3_mobile_det`

| Model | Time (ms) | Similarity |
|-------|-----------|------------|
| **en_v3_mobile** | **279** | **83.9%** |
| en_v4_mobile | 591 | 83.7% |

**Winner: en_v3_mobile** - faster with equivalent accuracy.

---

## 2. Image Width Optimization

Tested widths from 1000px down to 400px (original: 1752px).

| Width | Time (ms) | Similarity |
|-------|-----------|------------|
| 1000 | 332 | 82.6% |
| 900 | 315 | 82.3% |
| 800 | 274 | 83.9% |
| **700** | **260** | **84.5%** |
| 600 | 233 | 83.9% |
| 500 | 240 | 77.0% |
| 400 | 215 | 74.0% |

**Sweet spot: 600-800px**, with **700px** being optimal.

- Too large (>1000px): Slower, slightly lower accuracy
- Too small (<500px): Significant accuracy drop (text becomes unreadable)

---

## 3. Preprocessing Approaches

### What Works

| Approach | Similarity | Notes |
|----------|------------|-------|
| LANCZOS 700px (baseline) | 84.5% | Good baseline |
| **LANCZOS 700px + Gaussian blur 3x3** | **85.2%** | +0.7% improvement |
| **LANCZOS 700px + Gaussian blur 5x5** | **85.2%** | +0.7% improvement |
| LANCZOS 700px + Gaussian blur 7x7 | 84.8% | Blur too strong |

**Gaussian blur helps** by smoothing pixel edges, making characters look more like the smooth fonts the model was trained on.

### What Doesn't Work

| Approach | Similarity | Notes |
|----------|------------|-------|
| Raw (no preprocessing) | 70.9% | Baseline for comparison |
| Interpreter approach (300→1200px NEAREST) | 82.4% | Worse than simple LANCZOS |
| Dilation 2x2 | 84.2% | Characters become too thick |
| Dilation 3x3 | 83.3% | Characters blob together |
| Sharpening (unsharp mask) | 83.1% | Emphasizes pixel edges (bad) |
| Color inversion | 81.9% | Confuses the model |
| Bilateral filter | 84.2% | Edge preservation doesn't help |
| Grayscale | 84.7% | No improvement |
| BICUBIC resize | 84.6% | Similar to LANCZOS |
| BILINEAR resize | 84.7% | Similar to LANCZOS |

---

## 4. Key Insights

### Why Mobile > Server for Pixel Fonts
- Server models trained on documents/photos with anti-aliased, variable fonts
- Pixel fonts have sharp blocky edges, uniform grid, no anti-aliasing
- Mobile models are simpler and generalize better to unusual text styles
- Server detection completely fails on some low-text images

### Why Blur Helps
- Smooths out blocky pixel edges
- Makes characters look more like smooth fonts the model was trained on
- Too much blur (>5x5) degrades accuracy

### Why Resize to 700px Helps
- Brings pixel font to a size the model was trained on
- Reduces noise and processing time
- Too small loses detail, too large adds noise

### What Doesn't Help
- **Dilation**: Characters already thick enough, dilation causes merging
- **Sharpening**: Emphasizes pixel edges (opposite of what we want)
- **Inversion**: Model expects certain color patterns
- **Grayscale**: Color information doesn't hurt, removing it doesn't help
- **NEAREST upscale**: Preserves pixel edges (bad for recognition)

---

## 5. Comparison with Interpreter's Current Approach

The interpreter currently uses:
```python
DOWNSCALE_DIMENSION = 300
NEAREST_UPSCALE_FACTOR = 4
# Result: 300px → 1200px with NEAREST interpolation
```

Benchmark results:
| Approach | Similarity | Time |
|----------|------------|------|
| Interpreter (300→1200px NEAREST) | 82.4% | 370ms |
| **Optimized (LANCZOS 700px + blur)** | **85.2%** | **260ms** |

**Recommendation:** Update interpreter to use LANCZOS 700px + Gaussian blur 5x5 for +2.8% accuracy and 30% faster processing.

---

## 6. Post-Processing (Spell Check)

Tested pyspellchecker to correct OCR errors.

| Approach | Similarity | Improvement |
|----------|------------|-------------|
| No spell check (baseline) | 85.2% | - |
| pyspellchecker (all words) | 85.3% | +0.1% |
| pyspellchecker (skip capitalized) | 85.3% | +0.1% |

**Conclusion: Negligible benefit (+0.1%)**

### Why Spell Check Doesn't Help Much

1. **Game-specific proper nouns**: Character names like "Cless", "Alvein", "Arche" get incorrectly "corrected" to dictionary words ("Less", "Alvin", "Arch")
2. **Non-dictionary OCR errors**: Many OCR mistakes produce non-words that have no close dictionary match (e.g., "tuo" has no obvious correction)
3. **Already high accuracy**: At 85.2%, most words are already correct
4. **False positives offset gains**: Corrections that hurt accuracy roughly cancel out beneficial corrections

### Sample Corrections Made

| Original | Corrected | Verdict |
|----------|-----------|---------|
| tuo | - | No correction (good - "two" not close enough) |
| shoud | should | ✓ Helpful |
| Cless | Less | ✗ Harmful (character name) |
| Alvein | Alvin | ✗ Harmful (character name) |

**Recommendation**: Skip spell check for game text. The overhead isn't worth +0.1%.

---

## 7. Future Improvements

- **Fine-tune recognition model** on pixel font samples (~5000 labeled samples needed)
- **Try other OCR engines**: Tesseract, EasyOCR, TrOCR
- **Game-specific dictionary**: Build custom spell checker with game vocabulary (character names, items, etc.)

---

## 8. MeikiOCR Japanese Preprocessing

Benchmark conducted on 13 screenshots from Tales of Phantasia (Japanese version) to determine if preprocessing helps MeikiOCR.

### Results

| Preprocessing | Time (ms) | Similarity |
|---------------|-----------|------------|
| **lanczos_700_no_blur** | 37 | **100%** |
| **old_interpreter_300_nearest_4x** | 37 | **100%** |
| raw | 39 | 99.4% |
| lanczos_700_blur5 | 37 | 99.2% |

### Key Findings

1. **Blur hurts MeikiOCR**: Unlike PaddleOCR which benefits from Gaussian blur, MeikiOCR performs *worse* with blur (99.2% vs 100%). MeikiOCR was trained specifically on pixel fonts and handles sharp edges well.

2. **Preprocessing helps slightly**: LANCZOS 700px (no blur) achieves 100% vs 99.4% raw.

3. **Raw is already excellent**: 99.4% accuracy with no preprocessing overhead.

### Decision: Keep Raw Implementation

**We decided NOT to add preprocessing to MeikiOCR on main.** Rationale:

1. **Dataset bias risk**: All 13 test images are from one game (Tales of Phantasia). Optimizing for 700px LANCZOS might hurt games with different text sizes, resolutions, or font styles.

2. **99.4% is already excellent**: The 0.6% improvement doesn't justify the risk of regression on other games.

3. **Raw is most generalizable**: MeikiOCR was trained on diverse Japanese game text - it's designed to handle raw input without preprocessing.

4. **Simplicity**: No preprocessing means simpler code and no processing overhead.

### MeikiOCR vs PaddleOCR: Different Preprocessing Needs

| Aspect | PaddleOCR | MeikiOCR |
|--------|-----------|----------|
| Trained on | Documents, photos | Japanese game pixel fonts |
| Blur effect | Helps (+14%) | Hurts (-0.8%) |
| Optimal preprocessing | LANCZOS 700px + blur 5x5 | Raw (or LANCZOS 700px, no blur) |
| Why | Smooths pixel edges to look like training data | Already trained on pixel edges |

---

## 9. MeikiOCR Hybrid (Multilingual) Evaluation

Evaluated eriksonssilva's MeikiOCR fork which combines MeikiOCR detection with PaddleOCR ONNX recognition for multilingual support.

See GitHub issue: https://github.com/bquenin/interpreter/issues/210

### Results (English text)

| OCR Engine | Time (ms) | Similarity |
|------------|-----------|------------|
| **MeikiOCR Hybrid (en)** | **63** | 83.6% |
| PaddleOCR (optimized) | 279 | 83.9% |

**Finding**: Nearly identical accuracy (83.6% vs 83.9%) but **4x faster** (63ms vs 279ms).

### Status

Waiting for eriksonssilva to publish the fork to PyPI under a new package name. Git references can't be used in PyPI-published packages, so we can't adopt the fork until it's properly published.

---

## 10. Benchmark Scripts

- `ocr_benchmark.py` - PaddleOCR benchmark (model selection + preprocessing)
- `width_sweep.py` - Test different image widths for PaddleOCR
- `preprocess_benchmark.py` - Test preprocessing approaches for PaddleOCR
- `postprocess_benchmark.py` - Test spell check post-processing
- `meiki_japanese_benchmark.py` - MeikiOCR Japanese preprocessing benchmark
- `meiki_hybrid_benchmark.py` - MeikiOCR multilingual fork evaluation

Run with:
```bash
cd benchmark
uv run python ocr_benchmark.py
```
