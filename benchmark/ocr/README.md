# OCR benchmark

This benchmark compares OCR models before the application dependency is changed. It exercises the exact production path in src/interpreter/ocr.py, including BGRA-to-RGB conversion, MeikiOCR inference, confidence filtering, deduplication, spatial clustering, and the worker's space-joined region output.

The current corpus manifest has 105 entries, all captured from real games or game projects:

| Group | Images | Ground truth today | Purpose |
| --- | ---: | --- | --- |
| Historical benchmark branch | 13 | single review | Directional regression smoke test; one game only |
| Project EGG retro-PC pack | 68 | single review | 41 PC-88, 19 PC-98, and 8 Sharp X1 title, dialogue, menu, battle, and HUD frames |
| Curated SFC/Mega Drive sources | 16 | 15 single review, 1 unscored | Dragon Quest I, Chrono Trigger, Shining Force, Landstalker, Phantasy Star IV, and Madō Monogatari I |
| Other external internet sources | 8 | 4 single review, 1 draft, 3 unscored | Visual-novel, PC-88, non-Japanese, and vendor-demo diagnostics |

The 100 scoreable samples are all real screenshots. This is enough for a substantially broader directional comparison, but not enough to approve a model replacement by itself: all 100 references still have only one review, and there are currently zero independently verified real evaluation samples.

## Quick start

From the repository root on Windows:

~~~powershell
.\.venv\Scripts\python.exe benchmark\ocr\benchmark.py inventory
.\.venv\Scripts\python.exe benchmark\ocr\benchmark.py prepare --suite legacy-smoke --suite retro-real --suite retro-pc
.\.venv\Scripts\python.exe benchmark\ocr\benchmark.py matrix
~~~

The default matrix covers 96 scoreable game screenshots from the historical, curated-console, and retro-PC suites. It runs the installed baseline directly from .venv, forces its Hugging Face cache offline by default, then runs meikiocr==0.3.4 in a separate uv isolated/no-project environment and a separate model cache. It does not alter the application environment or dependency lock. Results go to the ignored benchmark/ocr/results directory.

Test another API-compatible package/version with:

~~~powershell
.\.venv\Scripts\python.exe benchmark\ocr\benchmark.py matrix --candidate "meikiocr==0.3.3"
~~~

To run the outside internet diagnostics too:

~~~powershell
.\.venv\Scripts\python.exe benchmark\ocr\benchmark.py prepare
.\.venv\Scripts\python.exe benchmark\ocr\benchmark.py matrix --suite internet --include-unscored
~~~

Draft and unscored images are timed and their predictions/regions are recorded, but they are never included in CER.
The four scoreable internet diagnostics can be added with `--suite internet`, but the vendor demo and diagnostic-only samples must not decide promotion.

Ground-truth transcription must be blind to benchmark output. A reference is frozen from the exact downloaded image before either the baseline or candidate is run. Reviewers may use lossless nearest-neighbor zoom to inspect the same pixels, but must not consult either model's prediction, a translation overlay, a walkthrough, or source text to fill uncertain or hidden characters. If the visible pixels do not determine the target text or a mixed layout has no defensible linear reading order, the image stays unscored.

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

Comparison fails closed unless both reports have the same manifest, local-file, and OCR-source hashes, workload-defining configuration, and ordered sample IDs. This keeps paired CER, exact match, latency, errors, and promotion-gate counts on one identical workload.

## Promotion rule

The comparison distinguishes a directional statistical outcome from a release decision. A candidate is not promotion-ready unless all of these hold:

1. The upper bound of the paired CER-delta 95% confidence interval is below zero.
2. Exact-match rate does not regress.
3. Candidate p95 stays under 500 ms and does not regress by more than 25%.
4. There are no inference errors.
5. At least 100 independently verified real evaluation/holdout images from at least five games are present.

The limits are CLI options, but lowering the corpus requirements simply to obtain a passing result defeats the benchmark.

## Building the real corpus

The source registry is corpus.json plus its project-egg.json source pack. The prepare command downloads or extracts images into the ignored data directory, verifies fixed SHA-256 hashes and dimensions, and writes data/corpus.lock.json. Source packs provide shared metadata while expanding to ordinary manifest samples before validation, selection, locking, or fingerprinting.

Synthetic images are deliberately excluded. The manifest validator accepts only HTTPS downloads and screenshots extracted from repository history; the benchmark has no image generator. Font rendering, artificial backgrounds, and constructed layouts do not represent the capture, scaling, compression, or typography distribution this application sees.

Third-party game screenshots are deliberately not committed. Their manifest entries retain the exact file URL, provenance page, host or publisher, hash, dimensions, and redistribution status. Even public-domain Wikimedia files use the same local-fetch path so the repository contains no mixed-origin image bundle.

The retro-PC source pack uses official [Project EGG PC-88](https://www.amusement-center.com/project/egg/console/hard.php?hard=PC-8801), [PC-98](https://www.amusement-center.com/project/egg/landing/hard.php?h=PC-9801), and [Sharp X1](https://www.amusement-center.com/project/egg/landing/hard.php?h=X1) pages. Frames with Project EGG command overlays, clipped text, or characters that could not be determined from the image pixels were rejected before references were frozen. The retained set spans 28 games and preserves each exact screenshot URL, catalog page, SHA-256, and dimensions.

The retro outside batch includes 12 commit-pinned Super Famicom captures from Jo-Mako's archived JRPG reading corpus: six Dragon Quest I frames and six Chrono Trigger frames. The Dragon Quest source-authored transcriptions were checked against the selected images. The archived Chrono transcript index does not reliably match its image numbering, so those frames were transcribed visually and explicitly remain single-review. Four additional Mega Drive captures come from official SEGA pages for Shining Force, Landstalker, Phantasy Star IV, and Madō Monogatari I.

The other outside batch includes two pinned screenshots from the [Light.vn repository](https://github.com/hsdk123/Light.vn), four individually marked public-domain PC-88 text screenshots from [Wikimedia Commons](https://commons.wikimedia.org/wiki/Category:Japanese-language_video_game_screenshots), a public-domain non-Japanese menu negative, and MeikiOCR's own [demo image](https://github.com/rtr46/meikiocr). The vendor demo is diagnostic only because training/tuning overlap is plausible.

For an image to become verified:

1. Keep the untouched full capture; create a separate sample if a crop or exclusion mask is part of the test.
2. Freeze an image-only transcription before inspecting output from any model under test. Never seed or correct a reference with a baseline or candidate prediction.
3. Transcribe every Japanese character plus associated Latin letters/digits that the application should pass through. Do not transcribe decorative icons such as selection arrows.
4. Preserve visible punctuation and elongated/repetition marks. Do not silently correct spelling in the game or reconstruct text from external scripts or context.
5. Mark partly hidden text, translation overlays, OCR boxes, Interpreter UI, and ambiguous mixed-layout ordering as unscored robustness data rather than guessing.
6. Have a second reviewer compare the transcription against the exact image without seeing model output. Record any intentional exclusions in annotation.notes.
7. Balance the verified set across dialogue, menus, battle/HUD, mixed layouts, tiny/blurred text, stylized fonts, vertical text, and no-text negatives.
8. Reserve a private holdout captured after candidate selection; public demos and model-project examples must never decide promotion.

Exact duplicates are rejected by SHA-256 today. Perceptual duplicate detection should be added before further growth or any promotion decision so adjacent frames cannot create false confidence.

## Current limitations

- The existing 13-image set is a single Tales of Phantasia sequence and its inherited ground truth has only one review.
- Every currently scoreable transcription still has only one independent review; none can satisfy the promotion gate yet.
- Bounding boxes are retained in result JSON, but the initial promotion metric is end-to-end text CER. Region-level IoU/precision/recall should be added once real boxes are double-annotated.
- Public internet images are useful evaluation material, not a genuinely secret holdout.
- URL-hosted assets can disappear or change upstream; preparation fails closed on a hash or dimension mismatch, but durable use may require permission to redistribute a frozen corpus.
- The built-in runner targets MeikiOCR-compatible packages. A different OCR architecture should emit the same result schema and use the existing compare command, while preserving identical application post-processing where applicable.

Run the non-networked unit tests with:

~~~powershell
.\.venv\Scripts\pytest.exe tests\test_ocr_benchmark.py
~~~
