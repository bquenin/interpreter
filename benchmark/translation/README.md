# Translation benchmark

This benchmark compares Japanese-to-English models before any production model is replaced. It keeps model inference, corpus creation, automatic scoring, and human review separate so a candidate cannot influence the test set or grade itself.

The latest reproducible run and decision are recorded in [`RESULTS.md`](RESULTS.md).

The primary workload is the text that a player would actually send from an old Japanese game: kana-heavy writing, unusual spacing, short menu labels, speaker names, punctuation, and longer dialogue. The runner calls the exact production `src/interpreter/translate.py::Translator.translate` implementation for the baseline, including the application's GPU bootstrap and output normalization. It clears the fuzzy translation cache before every measured call so every score and timing measures the model rather than a previous corpus entry.

## Frozen corpus

`sources.json` defines 268 aligned semantic pairs from eight real 8-bit/16-bit games and four independent fan-translation projects. `corpus.py prepare` downloads the exact files at full Git commit URLs, verifies raw-byte SHA-256 hashes, removes non-visible control/layout codes, excludes dynamic placeholders and debug metadata, and samples each game/type/length stratum by a fixed SHA-256 rank. It does all of this before a model runs.

| Platform | Games | Pairs |
|---|---|---:|
| Famicom Disk System | Famicom Detective Club: The Girl Who Stands Behind; The Missing Heir; Shin Onigashima; Time Twist; Yūyūki | 150 |
| NEC PC-9801 | Dragon Slayer: The Legend of Heroes | 50 |
| Sega Master System | Phantasy Star | 33 |
| Super Famicom | Metal Slader Glory: Director's Cut | 35 |

The selected set contains 188 dialogue, 70 menu, and 10 system pairs: 121 short, 78 medium, and 69 long. Every pair has a `screen` track. When the source project also supplies a kanji-normalized transcription, the same reference is expanded into a `normalized` diagnostic track. There are 268 screen samples and 136 distinct normalized samples, for 404 model calls per repeat. The screen track—not normalized prose—is the promotion metric.

The source projects are pinned to:

- [sudgy/nintendo_translations at `39f7fb4`](https://github.com/sudgy/nintendo_translations/tree/39f7fb43549ebc428f6216c27cbd81ed738ba3c2), which supplies exact display text, normalized Japanese, and English for five FDS games.
- [maxim-zhao/psrp at `2a327b7`](https://github.com/maxim-zhao/psrp/tree/2a327b7163eb7864c004ac2f46a00e66a88d2e1d), which supplies display/normalized Japanese plus literal and official-localization alternatives for Phantasy Star.
- [romh-acking/metal-slader-glory-sfc-en at `beb3e86`](https://github.com/romh-acking/metal-slader-glory-sfc-en/tree/beb3e86dec0fd928ac165eaa7b9bfe29358b03ea), which supplies aligned SFC script text and a fan translation.
- [nleseul/ds6_pc98_trans at `2d32f8f`](https://github.com/nleseul/ds6_pc98_trans/tree/2d32f8f93afa50dbe8003521624194a91a6f86a9), which supplies aligned PC-98 dialogue, menu, and battle text for Dragon Slayer: The Legend of Heroes.

These are public corpora, so unknown training contamination remains possible. Most references have only one source, and the Nintendo repository itself describes its translations as nonprofessional. Automatic results are therefore evidence for ranking and regression detection, not sufficient evidence to ship a model. The promotion gate requires at least 100 independently verified, model-blind human references across five games, a separate private holdout, and a blind human A/B result. `reviews.json` deliberately starts empty; AI review does not count as independent verification.

No synthetic text or generated screenshots are accepted. Downloaded source files, generated locks, model caches, raw results, and review packets live under ignored directories. Only the compact registries and tooling are committed.

## Models

`models.json` pins every repository to a full Hugging Face revision and pins its benchmark packages. The default overnight matrix is:

| ID | Model | Parameters/artifacts | Inference profile |
|---|---|---|---|
| `production` | [Sugoi V4 CTranslate2](https://huggingface.co/entai2965/sugoi-v4-ja-en-ctranslate2) | about 1.1 GB | Exact application path, beam 5 |
| `quickmt` | [QuickMT ja-en](https://huggingface.co/quickmt/quickmt-ja-en) | 200M/about 0.4 GB CT2 subset | Repository SentencePiece models, beam 5 |
| `lfm2-350m` | [LFM2-350M-ENJP-MT](https://huggingface.co/LiquidAI/LFM2-350M-ENJP-MT) | 350M/about 0.7 GB | Required `Translate to English.` system turn and documented sampling profile, deterministically seeded per source |
| `hy-mt-1.8b` | [HY-MT1.5-1.8B](https://huggingface.co/tencent/HY-MT1.5-1.8B) | 1.8B/about 4.1 GB | Documented no-explanation prompt and sampling profile, deterministically seeded per source |
| `riva-4b-v2` | [Riva-Translate-4B-Instruct-v2](https://huggingface.co/nvidia/Riva-Translate-4B-Instruct-v2) | 4B/about 8.4 GB | Required `ja-en` system turn, greedy decoding |

[TranslateGemma 4B](https://huggingface.co/google/translategemma-4b-it) is also registered and supported, but is excluded from the default matrix because its Gemma license must first be accepted on Hugging Face. Pass it explicitly after setting `HF_TOKEN`.

The transformer environments use the pinned CUDA 12.8 PyTorch index. QuickMT includes the same pip CUDA runtime packages the application uses for CTranslate2. Each candidate runs in a separate `uv --isolated --no-project` environment and a separate ignored Hugging Face cache, so the benchmark never edits the application environment or lock file. The report records the resolved revision, SHA-256 of every loaded artifact, package versions, actual device/dtype, peak PyTorch GPU allocation, application source hashes, and Git state.

Model licenses differ and are not interchangeable with the repository's MIT license. The comparison gate stays closed until the intended deployment license has been reviewed; a good metric does not grant redistribution rights.

## Run it

From the repository root on Windows:

```powershell
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\python.exe benchmark\translation\benchmark.py prepare
.\.venv\Scripts\python.exe benchmark\translation\benchmark.py inventory
.\.venv\Scripts\python.exe benchmark\translation\benchmark.py validate
.\.venv\Scripts\python.exe benchmark\translation\benchmark.py matrix
```

On macOS/Linux, replace `.\.venv\Scripts\python.exe` with `.venv/bin/python`.

The default matrix runs production plus all four accessible candidates, three timed repeats, two warm-ups, chrF++/BLEU, pinned WMT22 COMET, and a paired comparison for each candidate. It can download roughly 17 GB of model and metric artifacts. Raw and scored JSON reports go to ignored `benchmark/translation/results/`.

Useful smaller commands:

```powershell
# One deterministic smoke sample; no metric package required
.\.venv\Scripts\python.exe benchmark\translation\benchmark.py run `
  --model-id production --limit 1 --repeats 1 --warmups 0 `
  --output benchmark\translation\results\production-smoke.json

# Run only lightweight candidates and skip COMET
.\.venv\Scripts\python.exe benchmark\translation\benchmark.py matrix `
  --candidate quickmt --candidate lfm2-350m --skip-comet

# Run the gated candidate after accepting its terms
$env:HF_TOKEN = "..."
.\.venv\Scripts\python.exe benchmark\translation\benchmark.py matrix `
  --candidate translategemma-4b
```

Scoring is intentionally outside project dependencies:

```powershell
uv run --isolated --no-project --with sacrebleu==2.5.1 python `
  benchmark\translation\benchmark.py score result.json

uv run --isolated --no-project --with sacrebleu==2.5.1 python `
  benchmark\translation\benchmark.py compare baseline-scored.json candidate-scored.json
```

`compare` fails closed unless both reports have the same frozen corpus fingerprint, source/review/model registries, production translation and worker source hashes, benchmark runner files, workload settings, ordered IDs, exact sources, and references. Changing an ID while retaining different text is not enough to make reports comparable.

## Metrics and decision rule

The primary automatic statistic is the paired difference in per-sample chrF++ on the 268 screen-track pairs. Multiple legitimate references are scored together. A deterministic 10,000-resample paired bootstrap supplies a 95% confidence interval. First-reference corpus chrF++ and BLEU are secondary surface-form metrics; reference-based WMT22 COMET is an optional semantic cross-check. Reports also include:

- results by game, platform, dialogue/menu, source length, and normalized/screen track;
- model load time and per-call median/p95 latency;
- empty output, inference error, Japanese leakage, numeric-token preservation, and repeated-output determinism;
- model artifact footprint and, for PyTorch CUDA models, peak allocated VRAM.

A candidate is not promotion-ready unless the lower paired chrF++ confidence bound is above zero, no game regresses beyond the configured tolerance, reliability diagnostics pass, interactive latency and artifact budgets pass, and all reference/human/private/license gates pass. The limits are command options, but lowering them after seeing a candidate's output invalidates the decision.

chrF++ and BLEU remain imperfect for creative game localization. Speaker voice, gender, names, jokes, implied subjects, and terse menu context need bilingual review. COMET is learned and may share web-data biases. Treat agreement between metrics as stronger evidence, not a substitute for blind human judgments.

## Blind review

Create a randomized A/B sheet and a separate decoder key:

```powershell
.\.venv\Scripts\python.exe benchmark\translation\benchmark.py blind-packet `
  production-scored.json candidate-scored.json `
  --packet benchmark\translation\results\human-ab.csv `
  --key benchmark\translation\results\human-ab-key.json
```

Give reviewers only the CSV. They enter `A`, `B`, `TIE`, or `INVALID`; they should not see the key, model names, automatic scores, or source-project English. After collection:

```powershell
.\.venv\Scripts\python.exe benchmark\translation\benchmark.py blind-score `
  benchmark\translation\results\human-ab.csv `
  benchmark\translation\results\human-ab-key.json `
  --output benchmark\translation\results\human-ab-scored.json
```

The scorer verifies that source text and either translation were not edited after randomization and reports a Wilson 95% interval for decisive preferences. Reviewer-facing CSV cells are exported as text when a spreadsheet could interpret their prefix as a formula; the held key fingerprints both the canonical content and its safe CSV representation. Pass the score JSON to `compare --blind-review ...`. Reference verification is a different task and must be blind to all model outputs; create its sheet before results are shown with `reference-packet`.

## Production fuzzy-cache diagnostic

Model quality calls are uncached, but the application uses a 0.90 `SequenceMatcher` fuzzy cache in normal operation. Audit the frozen player-visible texts independently with:

```powershell
.\.venv\Scripts\python.exe benchmark\translation\benchmark.py cache-audit `
  --output benchmark\translation\results\cache-audit.json
```

This is a static worst-case collision check, not part of candidate scoring, because runtime behavior also depends on which recent screenshots are still in the cache.

## Tests

```powershell
.\.venv\Scripts\ruff.exe check benchmark\translation tests\test_translation_benchmark.py
.\.venv\Scripts\pytest.exe tests\test_translation_benchmark.py
```
