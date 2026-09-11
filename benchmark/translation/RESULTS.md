# Translation benchmark results — 2026-08-31

**Decision: keep the production Sugoi V4 model.** None of the four accessible candidates proved better on the primary player-visible-text metric, and none passed the predeclared deployment and evidence gates. No production model or setting was changed.

## Run identity

- Benchmark commit: `d33bae53656f04cbe0dcebecdfacba477026e14c`
- Corpus fingerprint: `8b03090234f41ce82ee737030dd0590674bb005acc1dc74b650ef9aa810b8d31`
- Workload: 268 independent `screen` pairs plus 136 `normalized` diagnostics; two warm-ups and three timed calls per model/sample
- Hardware: NVIDIA GeForce RTX 4070 Ti, Windows 11, Python 3.12.12; every model and COMET ran on CUDA
- Metrics: SacreBLEU 2.5.1 chrF++/BLEU and pinned `Unbabel/wmt22-comet-da` revision `2760a223ac957f30acfb18c8aa649b01cf1d75f2`
- Statistical test: paired 10,000-resample bootstrap over the 268 screen pairs, seed 1729

The command was:

```powershell
.\.venv\Scripts\python.exe benchmark\translation\benchmark.py matrix
```

Raw predictions and metric reports remain ignored because they are reproducible run artifacts. This file is the committed run summary.

## Primary screen-track result

Higher chrF++ and COMET are better. Deltas and confidence intervals are paired against production. Latency is synchronized end-to-end inference; artifact size excludes shared runtime packages.

| Model | chrF++ | Paired chrF++ delta (95% CI) | COMET | Paired COMET delta (95% CI) | Median / p95 | Artifact | Outcome |
|---|---:|---:|---:|---:|---:|---:|---|
| Production Sugoi V4 | 25.63 | — | 0.6068 | — | 41.8 / 244.0 ms | 1.03 GiB | Baseline |
| QuickMT 200M | 22.59 | −3.04 [−5.35, −0.73] | 0.5759 | −0.0309 [−0.0452, −0.0168] | 21.7 / 97.7 ms | 0.38 GiB | **Worse** |
| LFM2 350M | 23.33 | −2.30 [−4.62, +0.00] | 0.5946 | −0.0123 [−0.0278, +0.0033] | 307.7 / 1,426.1 ms | 0.66 GiB | Inconclusive |
| HY-MT 1.8B | 27.38 | +1.75 [−0.90, +4.44] | 0.6489 | +0.0421 [+0.0228, +0.0609] | 813.2 / 4,000.7 ms | 3.81 GiB | Inconclusive |
| Riva Translate 4B v2 | 25.79 | +0.15 [−2.11, +2.33] | 0.6361 | +0.0293 [+0.0136, +0.0451] | 537.3 / 3,005.4 ms | 7.80 GiB | Inconclusive |

HY-MT and Riva score significantly higher under COMET, but not under the declared primary chrF++ test. That disagreement is useful evidence for a later blind bilingual review, not grounds to select the favorable metric after seeing results. QuickMT is 2.5× faster and much smaller than production, but is significantly worse on both quality metrics.

## Coverage and regressions

Mean screen chrF++ delta by game shows why a corpus-wide point estimate is insufficient:

| Game | QuickMT | LFM2 | HY-MT | Riva |
|---|---:|---:|---:|---:|
| Dragon Slayer: The Legend of Heroes | −2.09 | −4.58 | −1.67 | −3.67 |
| Famicom Detective Club: The Girl Who Stands Behind | −5.78 | −3.76 | +5.95 | −1.86 |
| Famicom Detective Club: The Missing Heir | −8.59 | −5.81 | −2.83 | −0.56 |
| Shin Onigashima | +0.89 | +1.32 | +4.70 | +1.28 |
| Yūyūki | +2.05 | +3.30 | +10.12 | +9.18 |
| Metal Slader Glory: Director's Cut | −4.50 | −4.25 | −4.98 | −2.01 |
| Phantasy Star | −1.62 | −3.11 | +0.76 | −0.28 |
| Time Twist | −5.21 | +0.41 | +5.45 | +2.11 |

HY-MT therefore trips the greater-than-2 chrF++ regression guard on The Missing Heir and Metal Slader Glory despite having the best overall point estimate. Riva trips it on Dragon Slayer and Metal Slader Glory.

The normalized diagnostic confirms why the screen track must remain primary:

| Model | Normalized chrF++ | Normalized COMET |
|---|---:|---:|
| Production | 42.86 | 0.7808 |
| QuickMT | 38.75 | 0.7454 |
| LFM2 | 38.85 | 0.7638 |
| HY-MT | 42.88 | 0.7920 |
| Riva | 44.61 | 0.8030 |

Every model scores much better on normalized Japanese than on the kana-heavy text players and OCR actually provide. Ranking only normalized prose would materially overstate real-game quality.

## Reliability and promotion gates

Each of the five models completed 1,212 measured calls with zero inference errors, zero empty outputs, and zero nondeterministic samples. Production, QuickMT, and Riva had no Japanese-script leakage; LFM2 and HY-MT each left one source fragment untranslated. Numeric-token preservation was 15/19 for production, versus 10/19 QuickMT, 11/19 LFM2, 13/19 HY-MT, and 12/19 Riva. The numeric slice is small and should be expanded, but every candidate failed the predeclared no-regression check.

No candidate is promotion-ready. In addition to the automatic quality/latency/size blockers above, the deliberately fail-closed evidence gates still report:

- 0 independently verified references (100 required) across 0 verified games (5 required);
- 0 blind human A/B judgments (100 required);
- no separate private holdout result; and
- no completed deployment-license review.

The public corpora may overlap model training data, most references come from one nonprofessional fan translation, and valid localization alternatives can receive low surface-form scores. TranslateGemma 4B was not run because its gated Gemma terms have not been accepted for this environment. The next defensible evaluation step is independent bilingual reference review followed by a private holdout and blind production-vs-HY/Riva A/B test—not a model replacement.


---

# Addendum — Ollama candidates, 2026-09-10

**Decision: Sugoi V4 stays the built-in default. Sugoi 14B Ultra becomes the recommended model for the optional LLM-endpoint engine.** Both Ollama candidates beat production on the primary screen-track chrF++ test with confidence intervals well clear of zero, but they are 4.5x slower at p95, 7 to 8x larger, and still fail the predeclared evidence gates. They are only reachable through the user-supplied Ollama runtime, which is exactly what the LLM-endpoint engine (#262) was built for.

## Run identity

- Benchmark commit: `ea5d934` (adds the `ollama` adapter; corpus and metrics unchanged)
- Corpus fingerprint: `8b03090234f41ce82ee737030dd0590674bb005acc1dc74b650ef9aa810b8d31` (same as the August run)
- Workload: 268 `screen` pairs plus 136 `normalized` diagnostics; two warm-ups and three timed calls per model/sample
- Hardware: NVIDIA GeForce RTX 4070 Ti (12 GB), Windows 11, Ollama 0.33.3; both candidates fully resident on the GPU (49/49 layers offloaded), production on CUDA
- Candidates run through the exact application path (`src/interpreter/llm_translate.py`): application system prompt, Ollama native `/api/chat`, thinking disabled, temperature 0, fixed seed, no context replay
- Pins: Sugoi 14B Ultra GGUF Q4_K_M (Hugging Face `d8dd836bf519a604530779cbf5ce13ffb35c3eeb`, Ollama manifest `e4afea968d86…`), gemma3:12b Q4_K_M (Ollama manifest `f4031aab637d…`)
- Metrics and statistics as in the August run: chrF++/BLEU via SacreBLEU 2.5.1, pinned `Unbabel/wmt22-comet-da`, paired 10,000-resample bootstrap, seed 1729

The command was:

```powershell
.\.venv\Scripts\python.exe benchmark\translation\benchmark.py matrix --candidate sugoi-14b-ultra-q4 --candidate gemma3-12b-q4
```

## Primary screen-track result

| Model | chrF++ | Paired chrF++ delta (95% CI) | COMET | Paired COMET delta (95% CI) | Median / p95 | Wins / losses / ties | Artifact | Outcome |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Production Sugoi V4 | 25.63 | — | 0.6068 | — | 46.4 / 261.3 ms | — | 1.03 GiB | Baseline |
| Sugoi 14B Ultra Q4_K_M (Ollama) | 37.62 | +11.98 [+8.95, +15.08] | 0.7243 | +0.1175 [+0.0972, +0.1383] | 280.3 / 1,195.6 ms | 189 / 65 / 14 | 8.37 GiB | **Better** |
| Gemma 3 12B Q4_K_M (Ollama) | 34.00 | +8.37 [+5.15, +11.69] | 0.6974 | +0.0906 [+0.0699, +0.1123] | 290.7 / 1,165.6 ms | 170 / 85 / 13 | 7.59 GiB | **Better** |

Production numbers match the August run to the second decimal, which confirms the corpus and metric pipeline are unchanged. Both candidates are significantly better under both metrics, and this time the two metrics agree.

## Coverage and regressions

Mean screen chrF++ delta by game:

| Game | Sugoi 14B Ultra | Gemma 3 12B |
|---|---:|---:|
| Dragon Slayer: The Legend of Heroes | +2.23 | −0.11 |
| Famicom Detective Club: The Girl Who Stands Behind | +16.25 | +11.58 |
| Famicom Detective Club: The Missing Heir | +9.05 | +5.49 |
| Shin Onigashima | +11.37 | +14.79 |
| Yūyūki | +29.24 | +22.35 |
| Metal Slader Glory: Director's Cut | +1.20 | −2.73 |
| Phantasy Star | +14.94 | +8.29 |
| Time Twist | +19.59 | +14.79 |

Sugoi 14B Ultra improves every game. Gemma 3 12B trips the greater-than-2 chrF++ regression guard on Metal Slader Glory, the kanji-heavy Director's Cut text where the August candidates also struggled.

Normalized diagnostic:

| Model | Normalized chrF++ | Normalized COMET |
|---|---:|---:|
| Production | 42.86 | 0.7808 |
| Sugoi 14B Ultra | 45.94 | 0.8049 |
| Gemma 3 12B | 41.25 | 0.7848 |

The screen-versus-normalized gap shrinks for Sugoi 14B Ultra (37.6 vs 45.9) compared with production (25.6 vs 42.9): the larger model copes far better with the kana-only text that OCR actually delivers, which is the gap that matters in the application.

## Reliability

Both candidates completed 1,212 measured calls with zero errors and zero empty outputs. Sugoi 14B Ultra had no Japanese-script leakage; Gemma 3 12B leaked one source fragment on the normalized track. Numeric-token preservation was 13/19 for Sugoi 14B Ultra and 14/19 for Gemma 3 12B against 15/19 for production, so both trip the no-regression check on this small slice.

Despite temperature 0 and a fixed seed, Ollama produced more than one distinct output across the three repeats for 18 (Sugoi 14B) and 8 (Gemma 3) of the 268 screen samples. This is GPU batch-order nondeterminism in llama.cpp, not sampling, and the variants are near-identical wordings. It is worth knowing for the application (the fuzzy translation cache hides it in practice) and is recorded as a blocker by the promotion gate.

## Promotion gates

Neither candidate is promotion-ready as a replacement default, and neither could be: a 4.5x p95 latency ratio, 7 to 8x artifact size, the nondeterminism above, and the unchanged evidence gates (0 independently verified references, 0 blind judgments, no private holdout, no completed license review) all block. Sugoi 14B Ultra is Apache-2.0, so its license review is the easy one.

What this run does establish is the recommendation for the optional LLM-endpoint engine: a user with roughly 10 GB of VRAM who runs `ollama pull hf.co/sugoitoolkit/Sugoi-14B-Ultra-GGUF:Q4_K_M` gets a large, consistent quality gain over the built-in model at about 0.3 s per line. The next defensible steps remain independent bilingual reference review and a blind A/B test, now with Sugoi 14B Ultra as the candidate worth spending that effort on.
