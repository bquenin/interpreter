# OCR benchmark

This benchmark compares OCR models before the application dependency is changed. It exercises the exact production path in src/interpreter/ocr.py, including BGRA-to-RGB conversion, MeikiOCR inference, confidence filtering, deduplication, spatial clustering, and the worker's space-joined region output.

The current corpus manifest has 44 entries:

| Group | Images | Ground truth today | Purpose |
| --- | ---: | --- | --- |
| Historical benchmark branch | 13 | single review | Directional regression smoke test; one game only |
| Community GitHub issues | 11 | 5 draft, 6 unscored | Real failures, 4K frames, menus/HUD, overlays, and app-UI contamination |
| External internet sources | 8 | 3 draft, 5 unscored | Visual-novel, PC-88, non-Japanese, and vendor-demo diagnostics |
| Deterministic controls | 12 | verified by construction | Pixel/modern fonts, menu/dialogue/HUD, low contrast, scaling, vertical text, and a no-text negative |

Only the 13 historical samples and 12 generated controls are scoreable initially. That is enough to test the machinery and find obvious regressions, but not enough to approve a model replacement. In particular, there are currently zero independently verified real evaluation samples.

## Quick start

From the repository root on Windows:

~~~powershell
.\.venv\Scripts\python.exe benchmark\ocr\benchmark.py inventory
.\.venv\Scripts\python.exe benchmark\ocr\benchmark.py prepare --suite legacy-smoke --suite synthetic
.\.venv\Scripts\python.exe benchmark\ocr\benchmark.py matrix
~~~

The matrix command runs the installed baseline directly from .venv, forces its Hugging Face cache offline by default, then runs meikiocr==0.3.4 in a separate uv isolated/no-project environment and a separate model cache. It does not alter the application environment or dependency lock. Results go to the ignored benchmark/ocr/results directory.

Test another API-compatible package/version with:

~~~powershell
.\.venv\Scripts\python.exe benchmark\ocr\benchmark.py matrix --candidate "meikiocr==0.3.3"
~~~

To run the issue and internet diagnostics too:

~~~powershell
.\.venv\Scripts\python.exe benchmark\ocr\benchmark.py prepare
.\.venv\Scripts\python.exe benchmark\ocr\benchmark.py matrix --suite community-clean --suite community-robustness --suite internet --include-unscored
~~~

Draft and unscored images are timed and their predictions/regions are recorded, but they are never included in CER.

## What is measured

- Corpus-level (micro) character error rate: substitutions + deletions + insertions divided by reference characters.
- Macro CER, exact-match rate, and the three edit types separately.
- Empty-image false positives.
- Median, mean, and p95 warm-model latency; model loading is timed separately.
- Determinism across repeated runs.
- Per-image predictions, regions, timings, source tags, and per-suite summaries.
- Paired baseline/candidate wins, losses, and ties.
- A paired bootstrap 95% confidence interval for candidate CER minus baseline CER.

Text is normalized with Unicode NFKC and whitespace is ignored. Content and punctuation remain significant. This handles full-width ASCII and the fact that the application joins detected regions with spaces without forgiving real OCR mistakes.

Every report records the Interpreter OCR source hash, Git commit/dirty state, package versions, ONNX provider, platform, manifest fingerprint, every local image hash, and the resolved model snapshot and ONNX SHA-256 where available.

## Promotion rule

The comparison distinguishes a directional statistical outcome from a release decision. A candidate is not promotion-ready unless all of these hold:

1. The upper bound of the paired CER-delta 95% confidence interval is below zero.
2. Exact-match rate does not regress.
3. Candidate p95 stays under 500 ms and does not regress by more than 25%.
4. There are no inference errors.
5. At least 100 independently verified real evaluation/holdout images from at least five games are present.

The limits are CLI options, but lowering the corpus requirements simply to obtain a passing result defeats the benchmark.

## Building the real corpus

The source registry is corpus.json. The prepare command downloads or extracts images into the ignored data directory, verifies fixed SHA-256 hashes and dimensions, downloads pinned open-font resources, generates deterministic controls, and writes data/corpus.lock.json.

Third-party game screenshots are deliberately not committed. Their manifest entries retain the issue/file URL, uploader, hash, dimensions, and redistribution status. Even public-domain Wikimedia files use the same local-fetch path so the repository contains no mixed-origin image bundle.

The first community batch came from:

- Interpreter issue [#176](https://github.com/bquenin/interpreter/issues/176): five clean Dragon Knight II/III frames and three contaminated/configuration frames.
- Interpreter issue [#173](https://github.com/bquenin/interpreter/issues/173): one 4K PCSX2 frame with an existing English overlay.
- Interpreter issue [#149](https://github.com/bquenin/interpreter/issues/149): two Super Robot Wars diagnostic/configuration captures.

The outside batch includes two pinned screenshots from the [Light.vn repository](https://github.com/hsdk123/Light.vn), four individually marked public-domain PC-88 text screenshots from [Wikimedia Commons](https://commons.wikimedia.org/wiki/Category:Japanese-language_video_game_screenshots), a public-domain non-Japanese menu negative, and MeikiOCR's own [demo image](https://github.com/rtr46/meikiocr). The vendor demo is diagnostic only because training/tuning overlap is plausible.

For an image to become verified:

1. Keep the untouched full capture; create a separate sample if a crop or exclusion mask is part of the test.
2. Transcribe every Japanese character plus associated Latin letters/digits that the application should pass through. Do not transcribe decorative icons such as selection arrows.
3. Preserve visible punctuation and elongated/repetition marks. Do not silently correct spelling in the game.
4. Mark partly hidden text, translation overlays, OCR boxes, and Interpreter UI as unscored robustness data rather than guessing.
5. Have a second reviewer compare the transcription at native resolution. Record any intentional exclusions in annotation.notes.
6. Balance the verified set across dialogue, menus, battle/HUD, mixed layouts, tiny/blurred text, stylized fonts, vertical text, and no-text negatives.
7. Reserve a private holdout captured after candidate selection; public demos and model-project examples must never decide promotion.

Exact duplicates are rejected by SHA-256 today. Before the corpus grows substantially, add perceptual duplicate detection so adjacent video frames do not create false confidence.

## Current limitations

- The existing 13-image set is a single Tales of Phantasia sequence and its inherited ground truth has only one review.
- Generated controls are excellent for controlled regressions but are not representative enough to determine model quality.
- Bounding boxes are retained in result JSON, but the initial promotion metric is end-to-end text CER. Region-level IoU/precision/recall should be added once real boxes are double-annotated.
- Public issue and internet images are useful evaluation material, not a genuinely secret holdout.
- The built-in runner targets MeikiOCR-compatible packages. A different OCR architecture should emit the same result schema and use the existing compare command, while preserving identical application post-processing where applicable.

Run the non-networked unit tests with:

~~~powershell
.\.venv\Scripts\pytest.exe tests\test_ocr_benchmark.py
~~~
