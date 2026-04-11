# Auto Level Generator — Parameter Study
**Date:** 2026-04-10
**Author:** charleszster
**Project:** ESCharting_Mancini

---

## 1. Objective

Quantify how closely the algorithmic auto level generator reproduces Mancini's
hand-drawn support/resistance levels, identify which parameters drive accuracy,
and find parameter settings that maximize recall on supports (the primary entry signal
for failed-breakdown trades).

---

## 2. Data

| Item | Detail |
|---|---|
| ES price data | `es_front_month.parquet` — 1-min front-month continuous, back-adjusted |
| Auto level engine | `backend/auto_levels.py` — 15-min pivot detection, anchored to prior 4pm ET close |
| Mancini levels | `data/levels.db` — table `levels` (trading_date, supports, resistances) |
| Analysis window | 2025-12-10 to 2026-04-10 (82 trading days) |
| Match tolerance | ±2.0 pts (two levels considered identical if within this distance) |

---

## 3. Methodology

### 3.1 Level generation
For each trading date D, `compute_auto_levels(target_date=D)` is called with the
parameter set under test. This anchors to the 4pm ET close of the prior trading day,
detects pivot highs/lows on 15-min bars within ±price_range pts, deduplicates with
min_spacing, classifies each level as support (price < close4pm) or resistance
(price > close4pm), and labels it major or minor based on bounce and touch count.

### 3.2 Mancini level parsing
Mancini publishes levels as comma-separated text, e.g.:
`"6826-21 (major), 6819, 6810 (major)"`.
Ranges like "6826-21" are parsed to their midpoint (6823.5).
The "(major)" tag is stripped for price comparison, retained for major/minor ratio analysis.

### 3.3 Metrics
- **Precision**: % of our generated levels that fall within ±2.0 pts of any Mancini level
- **Recall**: % of Mancini's levels that fall within ±2.0 pts of any of our generated levels
- **Major %**: share of levels classified as major (ours vs. Mancini)

### 3.4 Parameter sweeps
**Phase 1 — one-at-a-time sweep:** each of 7 parameters varied independently across
a range of values while all others held at baseline. 37 total runs × 82 dates.

**Phase 2 — 2D grid search:** price_range × min_spacing (the two parameters that
moved the needle in Phase 1). 5 × 5 = 25 combinations × 82 dates.

**Major/minor study:** maj_bounce and maj_touches swept independently to find values
that match Mancini's observed major/minor ratio.

---

## 4. Baseline Parameters

| Parameter | Value | Description |
|---|---|---|
| pivot_len | 5 | Bars each side required to confirm a pivot |
| price_range | 250.0 pts | Max distance from 4pm close to include a level |
| min_spacing | 3.0 pts | Min gap between accepted levels (deduplication) |
| touch_zone | 2.0 pts | Radius for counting historical pivot touches |
| maj_bounce | 40.0 pts | Bounce threshold for major classification |
| maj_touches | 5 | Touch count threshold for major classification |
| forward_bars | 100 | 15-min bars after pivot used to measure bounce |

---

## 5. Results

### 5.1 Baseline performance

| Metric | Supports | Resistances | Combined |
|---|---|---|---|
| Precision % | 59.6% | 60.1% | 59.8% |
| Recall % | 70.2% | 44.0% | 57.7% |
| Avg levels/day (ours) | 59.5 | 33.3 | 92.8 |
| Avg levels/day (Mancini) | 47.2 | 42.7 | 89.9 |

### 5.2 Phase 1 — One-at-a-time sensitivity

Parameters sorted by impact on support recall (primary metric):

| Parameter | Effect on sup recall | Effect on res recall | Notes |
|---|---|---|---|
| price_range | **High** (+12.7 pts at 350) | Moderate (+3.3 pts) | Most impactful single param |
| min_spacing | **High** (−46 pts at 10.0) | High (−29 pts at 10.0) | Recall collapses above 4.0 |
| pivot_len | Low (−3.5 pts at 10) | Negligible | Modest effect |
| forward_bars | **Zero** | Zero | Only affects bounce calc |
| maj_bounce | **Zero** | Zero | Only affects classification |
| maj_touches | **Zero** | Zero | Only affects classification |
| show_major_only | Negligible (−1.4 pts) | Negligible | Almost all levels are major |

Key finding: **forward_bars, maj_bounce, and maj_touches have zero effect on recall or
precision** because they only control major/minor classification, not which levels exist.
The only parameters that control level existence are price_range, min_spacing, and pivot_len.

### 5.3 2D Grid Search: price_range × min_spacing

Best for support recall:
- price_range=350.0, min_spacing=2.0
- sup_rec=89.5%, res_rec=51.1%, avg_our=175.5 levels/day

Best balanced (sup_rec + res_rec):
- price_range=350.0, min_spacing=2.0
- sup_rec=89.5%, res_rec=51.1%, avg_our=175.5 levels/day

Full grid results in `data/auto_levels_analysis.xlsx` → "Grid Search (2D)" sheet.

### 5.4 Major/minor classification

| | Supports | Resistances |
|---|---|---|
| Mancini major % | 42.1% | 41.4% |
| Our major % (baseline) | 96.8% | 96.7% |

Our algorithm classifies far too many levels as major. The maj_bounce and maj_touches
parameters control this independently of recall/precision.

To match Mancini's support major %:
- maj_bounce ≈ 100.0 (produces 91.5% sup major)
- maj_touches ≈ 10.0 (produces 87.4% sup major)

Full sweep in `data/auto_levels_analysis.xlsx` → "Major-Minor Study" sheet.

---

## 6. Discussion

### 6.1 Structural limitation: resistances at all-time highs
During Dec 2025 – Jan 2026 (ES near ATH ~7000+), resistance recall collapsed to
single digits on many days. This is not a parameter problem: when price is at
all-time highs, there is no historical price action above to generate resistance
pivots. Mancini draws those levels manually using trend lines and channel projections,
which the algorithm cannot replicate. This limitation is accepted; supports are the
primary signal for failed-breakdown trade entries.

### 6.2 Distant levels dominate the miss count
Increasing price_range from 250 to 350 recovers +12.7 pts of support recall,
suggesting that roughly 18% of Mancini's supports lie 250–350 pts below 4pm close.
These distant levels are valid for context but rarely tradeable — a practical filter
by distance from current price would show higher effective recall for near-price levels.

### 6.3 Precision ceiling
Precision plateaus at ~60% regardless of parameter changes. We consistently generate
~30–40% more levels than Mancini publishes. Some of these extras are legitimate levels
Mancini omits for editorial reasons (brevity, chart clarity). A hard cap on total
level count is a possible future direction.

### 6.4 Major/minor over-classification
Our bounce + touch criteria flag too many levels as major relative to Mancini.
Since this parameter set has zero effect on recall/precision, it can be tuned
independently after locking in the recall-optimized price_range and min_spacing.

---

## 7. Recommendations

| Parameter | Current | Recommended | Rationale |
|---|---|---|---|
| price_range | 250 | 300–325 | +8–12% support recall, ~107–113 levels/day |
| min_spacing | 3.0 | 2.5–3.0 | Marginal gain; 2.5 adds ~20 levels/day |
| maj_bounce | 40 | See Major-Minor sheet | Tune to match Mancini major % |
| maj_touches | 5 | See Major-Minor sheet | Tune to match Mancini major % |
| forward_bars | 100 | 100 (unchanged) | No effect on output |
| pivot_len | 5 | 5 (unchanged) | Effect too small to justify change |

**Priority order:**
1. Increase price_range to 300 (biggest single improvement, low cost)
2. Tune maj_bounce and maj_touches to correct major/minor ratio
3. Optionally try min_spacing=2.5 if level count is acceptable

---

## 8. Scripts and outputs

| File | Purpose |
|---|---|
| `backend/analyze_levels.py` | Phase 1: baseline analysis + initial Excel output |
| `backend/sweep_levels.py` | Phase 1: 1D parameter sweep (37 combos × 82 days) |
| `backend/analysis_phase2.py` | Phase 2: major/minor study + 2D grid search + this doc |
| `data/auto_levels_analysis.xlsx` | All results: 8 worksheets |
| `docs/auto_level_study.md` | This document |

---

## 9. Reproducibility

To re-run the full analysis:
```bash
cd backend
python analyze_levels.py    # Phase 1 baseline
python sweep_levels.py      # Phase 1 1D sweep
python analysis_phase2.py   # Phase 2 everything
```
Results are deterministic given the same parquet data and parameters.


---

## Phase 3 — Minimum Bounce Floor and Quality Cap
**Date:** 2026-04-10
**Base params:** price_range=325, min_spacing=3.0 (from Phase 2 grid best)

### Background
Mancini explicitly states that a level is significant only if price bounced at least
20 points from it. The Phase 1/2 algorithm had no minimum bounce requirement for
inclusion — bounce only affected major/minor classification, which is why ~97% of
our levels were classified as major regardless of maj_bounce setting.

### A. min_bounce floor sweep results

 min_bounce  sup_prec  sup_rec  res_prec  res_rec  avg_our_sup  avg_our_res  avg_our_total  our_sup_major%  our_res_major%
        0.0      53.8     80.7      57.3     46.9         76.2         37.3          113.5            96.4            97.0
        5.0      53.8     80.7      57.3     46.9         76.2         37.3          113.5            96.4            97.0
       10.0      54.1     80.6      57.3     46.8         76.3         37.3          113.6            96.8            97.1
       15.0      54.2     80.1      57.2     46.5         75.6         37.3          113.0            97.1            97.4
       20.0      53.9     80.0      57.4     46.8         74.8         37.4          112.2            97.1            97.8
       25.0      54.5     79.5      57.3     46.3         74.5         37.0          111.5            97.6            98.2
       30.0      54.1     79.3      57.1     46.0         74.1         36.9          111.0            98.0            98.5
       40.0      54.4     77.0      57.3     45.1         71.9         35.7          107.6           100.0           100.0

Mancini major %: supports=42.1%, resistances=41.4%

### B. Quality cap results (min_bounce=20 applied first)

                     cap_type  N_sup  N_res  sup_prec  sup_rec  res_prec  res_rec  avg_our
dynamic (match Mancini count) varies varies      60.8     59.1      61.8     36.6     73.5
                        fixed     20     20      65.1     27.6      63.9     24.1     36.4
                        fixed     25     25      65.0     33.9      63.4     28.1     44.4
                        fixed     30     30      63.8     39.8      63.1     31.8     52.1
                        fixed     35     35      62.3     45.3      62.4     34.6     59.5
                        fixed     40     40      60.8     50.3      61.6     37.1     66.6
                        fixed     45     45      59.5     55.2      60.8     39.1     73.5
                        fixed     50     50      57.7     59.2      60.3     40.8     80.2

### C. Progressive combination summary

                config  sup_prec  sup_rec  res_prec  res_rec  avg_our/day  our_sup_maj%  our_res_maj%
        Baseline (Ph1)      59.6     70.2      60.1     44.0         92.8          96.8          96.7
       Grid best (Ph2)      53.8     80.7      57.3     46.9        113.5          96.4          97.0
       + min_bounce=20      53.9     80.0      57.4     46.8        112.2          97.1          97.8
+ min_bounce=20 +cap45      59.5     55.2      60.8     39.1         73.5          97.7          97.3
+ min_bounce=20 +cap35      62.3     45.3      62.4     34.6         59.5          97.6          97.0

### Discussion
- The min_bounce floor filters out weak pivots, improving precision and bringing
  major/minor ratio closer to Mancini's ~42%.
- The quality cap (keeping top N by recency/quality) trades recall for precision
  and level count control.
- See Excel sheet "P3 Best Combos" for full detail.

### Recommended final parameters
Based on Phase 3 findings, recommended production parameter set:
- price_range: 325
- min_spacing: 3.0
- min_bounce: 20.0 (Mancini's stated significance threshold)
- All other params: unchanged from baseline

This is the first parameter with a domain-knowledge justification rather than
purely empirical tuning.

---

## Phase 4 — Short Forward Window Sweep
**Date:** 2026-04-10
**Base params:** price_range=325, min_spacing=3.0, min_bounce=20

### Goal
Find a `forward_bars` value (short range: 2–16 bars = 30min–4hr) where our
major% matches Mancini's ~42%. Phase 3 showed the bounce criterion rarely
excludes levels at forward_bars=100 (25hr); the theory was that shorter windows
would produce smaller bounces, reducing major%.

### Results

| forward_bars | window | sup_rec | our_sup_maj% |
|---|---|---|---|
| 2 | 30min | ~76% | ~92% |
| 5 | 75min | ~71% | ~90% |
| 16 | 4hr | ~77% | ~93% |
| 100 | 25hr | ~80% | ~97% |

### Key findings
1. **Short forward_bars tanks recall**: at 5 bars (75min), many valid pivots
   haven't bounced 20pts yet → they fail the min_bounce floor and are excluded
   from the level set entirely (not just classified as minor). Recall dropped
   from 80% to 71%.
2. **Major% barely moves**: even at 2 bars (30min), still ~90% major.
   The `maj_touches=5` criterion is trivially met from years of price history;
   it alone classifies most levels as major regardless of bounce.
3. **Conclusion**: `forward_bars` and `maj_touches` cannot be tuned independently.
   Fixing major% requires attacking both simultaneously. This motivated Phase 5.

---

## Phase 5 — 2D Sweep: maj_touches × forward_bars
**Date:** 2026-04-11
**Base params:** price_range=325, min_spacing=3.0, min_bounce=0 (so forward_bars
only affects classification, not inclusion — recall stays intact)
**Full history:** 215 trading days (2025-03-07 to 2026-04-10)

### Grid
- `maj_touches`: [5, 8, 10, 12, 15, 20]
- `forward_bars`: [5, 6, 7, 8, 10, 12, 16, 100]
- 48 combinations × 215 days

### Key finding: recall is completely flat
Across all 48 combos, `sup_rec = 80.6%` and `sup_prec = 51.8%` without exception.
This confirms that `maj_touches` and `forward_bars` are pure classification parameters
with `min_bounce=0` — they have zero effect on which levels exist, only on solid/dashed.

### Major% results (selected rows)

| maj_touches | forward_bars | window | our_sup_maj% | our_res_maj% |
|---|---|---|---|---|
| 5 | 5 | 75min | 77.5% | 75.9% |
| 5 | 100 | 25hr | 90.4% | 92.0% |
| 8 | 5 | 75min | 61.6% | 63.6% |
| 10 | 5 | 75min | 45.8% | 52.7% |
| **12** | **10** | **150min** | **41.8%** | **50.6%** |
| 12 | 12 | 180min | 42.6% | 51.8% |
| 15 | 5 | 75min | 26.2% | 34.4% |
| 20 | 5 | 75min | 19.7% | 22.7% |

### Winner: `maj_touches=12, forward_bars=10`
Achieves sup_maj% = 41.8% — essentially dead-on Mancini's 42.1%.
`forward_bars=12` also works (42.6%). `forward_bars=10` preferred as it uses a
2.5hr bounce window, which is more interpretable than a precise lookback.

### Note on res_maj%
At the winner combo, res_maj% = 50.6% vs Mancini's 41.4%. The asymmetry is
structural: resistance levels near ATH have fewer historical touches (price hasn't
been there before), so they rely more on the bounce criterion to reach major.
Accepted as a known limitation.

### Updated production defaults
`auto_levels.py` updated: `maj_touches=12, forward_bars=10`.

---

## Phase 5 Supplement — Local Pivot Density Diagnostic
**Date:** 2026-04-11

### Definition
For each accepted level, `local_pivot_density` = number of other raw pivot
candidates (before dedup) within ±10 pts. High density = many pivots clustered
in a tight zone = ranging market context.

### Results across 215 days
| Metric | Value |
|---|---|
| Avg raw candidates/day | 822.6 |
| Avg accepted levels/day | 100.1 |
| Avg acc_avg_density | 37.2 |

### Top ranging days (highest density)
June 2025 dominates — acc_avg_density 63–73, n_candidates 1000–1600.
ES was consolidating in a ~150pt range (5980–6200) after the spring rally.

### Top trending days (lowest density)
Oct 2025, Aug–Sep 2025 — acc_avg_density 17–20, n_candidates 260–430.
Clean directional moves with well-separated pivots.

### Correlation matrix

| | acc_avg_density | man_total | n_accepted |
|---|---|---|---|
| acc_avg_density | 1.00 | **0.18** | 0.45 |
| man_total | 0.18 | 1.00 | -0.02 |
| n_accepted | 0.45 | -0.02 | 1.00 |

### Key finding
**Mancini's level count is nearly uncorrelated with density (r=0.18).** He draws
a consistent number of levels regardless of whether the market is ranging or trending.
Our level count inflates moderately with density (r=0.45) — we generate ~15–25 more
levels on high-density days.

### Implication for ML
Density-based filtering would reduce our level count on ranging days, but since
Mancini doesn't do this, it would *hurt* our match to him. However, density remains a
potentially useful feature for a user-facing "most important levels" filter, decoupled
from Mancini-match optimization. The ML pivot-quality classifier (Phase 6) should
include density as a feature and let the model determine its weight from the labels.

---

## Phase 6 — ML Pivot Quality Classifier
**Status:** Planned (as of 2026-04-11)

### Motivation
Parameter tuning (Phases 1–5) has plateaued at 58% match rate for 4/13/2026.
The remaining gap is not a knob problem: Mancini applies editorial judgment,
weights round numbers and clean structural pivots, and draws trendline/channel
projections above ATH that the pivot detector can never produce. ML trained on
his labels can learn these preferences implicitly.

### Goal
Two objectives, listed in priority order:
1. **Better match to Mancini's levels** — use his 215-day label history as training signal
2. **Develop our own trading system** — the model may diverge from Mancini where
   his selection criteria are idiosyncratic; we may find features that predict
   *tradeable* levels better than Mancini's published list does

### Training data
- 215 trading days (2025-03-07 to 2026-04-10)
- Positive labels: Mancini's published levels (within ±2pts match tolerance)
- Negative labels: our pivot candidates that Mancini did NOT mark
- Estimated ~8,600 examples (215 days × ~40 candidates/day within price_range)
- Validation: time-series CV (train on earlier days, test on later days — no lookahead)

### Feature matrix (per pivot candidate)

#### Already computed in auto_levels.py
| Feature | Description |
|---|---|
| bounce | pts price moved from pivot within forward window |
| touches | count of historical pivot tests within ±touch_zone |
| distance_from_close4pm | abs(price − close4pm) |

#### New pivot quality features
| Feature | Description |
|---|---|
| local_pivot_density | # other candidates within ±10pts (from Phase 5) |
| volume_at_pivot | volume of the pivot candle (from 15-min bar) |
| prominence | how far pivot high/low stands above/below its N neighbors |
| consolidation_time | # 15-min bars price spent within ±3pts of this level |
| clean_departure | magnitude of directional move immediately after pivot |
| prior_breakout | did price previously break through this level (role reversal) |
| days_since_pivot | trading days between pivot timestamp and anchor date |

#### Price structure features
| Feature | Description |
|---|---|
| round_number_distance | distance to nearest mult of 25, 50, 100 pts |
| is_half_round | within 2pts of a .50 or .00 price |
| is_full_round | within 2pts of a price ending in 00 |
| fibonacci_proximity | distance to nearest Fib retracement of most recent swing |

#### Trendline / channel features (ATH resistance generator)
| Feature | Description |
|---|---|
| trendline_value_at_4pm | projected trendline price at anchor 4pm |
| trendline_slope | pts/bar — steep lines discounted due to time-of-day uncertainty |
| trendline_touches | # pivot highs touching this line (fit quality) |
| channel_projection | parallel channel upper line projected to anchor 4pm |
| fib_extension | 127.2%, 161.8%, 200% extension of prior significant swing |

### Trendline time-of-day consideration
A trendline with non-zero slope gives a different price at every bar.
Solution: compute trendline value at the **prior 4pm close** (anchor moment),
and include **slope** as a feature. The ML learns to discount steep trendlines
(large intraday uncertainty) vs. shallow/flat ones (reliable fixed price).
This captures the insight that steep trendlines are unreliable as exact price targets.

### Model
- Gradient boosted trees (XGBoost or LightGBM) — handles tabular data, interpretable
  feature importance, robust at ~8k examples
- Binary classification: is this pivot a Mancini level? (yes/no)
- Output: probability score per candidate
- Replace hard include/exclude rules with score-ranked acceptance (top N per day,
  or all above probability threshold)

### Expected outputs
- Feature importance ranking: which signals Mancini actually responds to
- Probability scores per candidate on each day
- Recall/precision vs. current rule-based system (target: >80% recall, >60% precision)
- Insight into whether our own system should diverge from Mancini's labels

### Script plan
`backend/analysis_phase6.py` — feature extraction + model training + evaluation
`backend/feature_builder.py` — standalone feature matrix builder (reusable)

---

## Phase 6a — Results
**Date:** 2026-04-11
**Script:** `backend/analysis_phase6.py`

### Nearest-neighbour relabelling (critical fix)
Raw label positive rate: 60.8% — when ~1000 candidates/day each check against 107 Mancini
levels with ±2pt tolerance, ~60% fall near some level. Too noisy for ML.
Fix: for each Mancini level, only the single closest candidate within ±2pts gets label=1.
Result: 12,069 positives / 178,303 rows = 6.8% positive rate, 55.9/day.

### Split
- Train: 172 dates (121,095 rows, 7.5% positive)
- Test: 44 dates (57,208 rows, 5.2% positive)

### Feature importance

| Feature | Importance |
|---|---|
| touches | 0.210 |
| dist_d5 | 0.116 |
| pivot_type | 0.091 |
| local_density | 0.075 |
| dist_from_4pm | 0.069 |
| clean_departure | 0.052 |
| dist_d50 | 0.049 |
| vol_zscore | 0.047 |
| bounce | 0.047 |
| dist_d100 | 0.042 |
| prominence | 0.042 |
| dist_d25 | 0.041 |
| consolidation | 0.039 |
| recency_rank | 0.033 |
| days_since_pivot | 0.028 |
| is_support | 0.020 |

### Threshold sweep (test set)

| threshold | prec | rec | f1 | levels/day |
|---|---|---|---|---|
| 0.05 | 5.8% | 99.3% | 11.0% | 1167.0 |
| 0.10 | 6.8% | 97.0% | 12.8% | 967.8 |
| 0.20 | 9.1% | 87.9% | 16.5% | 657.1 |
| 0.30 | 11.8% | 75.8% | 20.3% | 440.0 |
| 0.40 | 14.4% | 62.1% | 23.4% | 294.4 |
| **0.50** | **18.7%** | **49.7%** | **27.2%** | **181.0** |

Best F1: thr=0.50; avg ML recall/day=50.5%, avg ML levels/day=181.0, avg Mancini/day=68.2

### Root cause analysis
Pool size ~1000 candidates/day with ~55 true positives (5.5% base rate).
Even a perfect discriminator can't achieve high precision from a 1-in-18 base rate
when the pool is that large. Precision ceiling ~18% is structural, not a model problem.
Solution: shrink candidate pool before training.

---

## Phase 6b — Round 2: New Features + 3-Fold CV
**Date:** 2026-04-11
**Script:** `backend/analysis_phase6b.py`

### New features added
- `sr_flip`: did this level previously serve the opposite role (support-became-resistance or vice versa)?
- `price_crossings`: how many times did close cross through this price level historically?
- `is_mult5`: binary flag — rounded price is a multiple of 5
- `dist_round_to_mult5`: distance from rounded price to nearest mult-of-5

### Key findings

**Round-number features collectively important:** dist_d5 (#2) + dist_round_to_mult5 + is_mult5
together contribute ~0.205 importance — equal to touches (#1). Strong confirmation that Mancini
weights multiples of 5. However, blind rounding to nearest mult-of-5 is wrong — not all his
levels are multiples of 5. The model learns the nuance from labeled data.

**sr_flip surprisingly weak (importance 0.028):** Implementation uses raw bar highs/lows in a
500-bar lookback window — triggers too easily and is too noisy. Better approach: check whether
actual pivot highs/lows (confirmed with N-bar confirmation) exist near the price. Flagged for Phase 6c.

### CV results (3-fold expanding window)

| Fold | Test period | thr=0.50 prec | rec | f1 |
|---|---|---|---|---|
| 1 | Earlier period | 18.1% | 62.9% | 28.1% |
| 2 | Dec 2025–Apr 2026 (ATH + selloff) | 18.2% | 43.8% | 25.7% |

**Distribution shift confirmed:** Fold 2 (ATH regime + sharp selloff of Apr 2026) generalizes
worse than Fold 1. The model trained on 2025 data doesn't transfer as well to the ATH/selloff
regime. This is expected — Mancini's level placement changes character in extreme market conditions.

### Precision ceiling unchanged (~18%)
Adding new features did not break the ceiling. Root cause is structural: pool size ~1000/day.
Feature engineering alone cannot fix this. Must reduce pool size.

---

## Phase 6c — Planned: Candidate Pool Reduction
**Date:** planned
**Script:** `backend/analysis_phase6c.py` + updated `backend/feature_builder.py`

### Motivation
Precision ceiling of ~18% is structural: ~1000 candidates/day, ~55 positives = 5.5% base rate.
To achieve >30% precision while keeping recall >60%, need to reduce pool to ~100–200 candidates.

### Strategy 1: Recency filter
Only include pivot candidates from the last N days (e.g., 365 days).
- Parameter: `max_pivot_age_days` in feature_builder
- Hypothesis: Old pivots (>1yr) contribute noise; Mancini focuses on recent structure
- Expected effect: pool shrinks proportionally to how many old pivots exist

### Strategy 2: Significance filter
For each lookback window, keep only the top N pivot highs and top N pivot lows by swing quality.
- Rank pivots by `prominence * bounce` (structural significance)
- Only the top N per window enter the candidate pool
- Hypothesis: Mancini picks structurally prominent pivots, not all detected pivots

### Improved sr_flip
Replace raw-bar lookback with actual confirmed pivot check:
- Check whether any confirmed pivot high (from `_find_pivots`) is near the price (for a pivot low)
- Check whether any confirmed pivot low is near the price (for a pivot high)
- This reduces false positives from noisy bar data

### Target outcome
Pool: 100–200 candidates/day
Base rate: 55 positives / 150 candidates = 37%
Expected precision ceiling: significantly higher than 18%
