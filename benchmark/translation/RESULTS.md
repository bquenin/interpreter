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
