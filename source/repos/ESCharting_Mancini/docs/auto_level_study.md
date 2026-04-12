# Auto Level Generator — Research Study
**Project:** ESCharting_Mancini  
**Data:** 216 trading days, 2025-03-07 to 2026-04-13  
**Status:** Complete — one structural gap remains (ATH cluster detection)

---

## 1. Objective

Reproduce Mancini's hand-drawn ES support/resistance levels algorithmically. His levels serve as entry signals for failed-breakdown trades; high recall on supports is the primary metric. The work progressed through two distinct phases: parameter tuning (Phases 1–5) and ML scoring (Phase 6), followed by a post-integration study of the major/minor distinction (Phase 7).

---

## 2. Data

| Item | Detail |
|---|---|
| ES price data | `es_front_month.parquet` — 1-min front-month continuous, back-adjusted |
| Auto level engine | `backend/auto_levels.py` — 15-min pivot detection, anchored to prior 4pm ET close |
| Mancini levels | `data/levels.db` — table `levels` (trading_date, supports, resistances) |
| Study window | 2025-03-07 to 2026-04-13 (216 trading days) |
| Match tolerance | ±2.0 pts |

Mancini publishes levels as comma-separated text, e.g. `"6826-21 (major), 6819, 6810 (major)"`. Ranges are parsed to their midpoint. The `(major)` tag is preserved throughout for major/minor analysis.

---

## 3. Algorithm Overview

For each trading date D:
- Aggregate 1-min parquet to 15-min bars
- Find the most recent bar closing at 4:00 PM ET (`close4pm`) — the price reference for everything
- Detect pivot highs/lows using N bars of confirmation on each side (default N=5)
- Filter to pivots within ±325pts of `close4pm`, processed newest-first
- Deduplicate: skip any candidate within 3.0pts of an already-accepted level
- Classify as support (price < close4pm) or resistance (price > close4pm)
- Score each accepted level with the Phase 6e ML model; `major = score ≥ 0.5`

---

## 4. Parameter Tuning (Phases 1–5)

### 4.1 Phase 1 — Baseline and Sensitivity

Baseline parameters: price_range=250, min_spacing=3.0, pivot_len=5, forward_bars=100, maj_bounce=40, maj_touches=5.

| Metric | Supports | Resistances |
|---|---|---|
| Recall % | 70.2% | 44.0% |
| Precision % | 59.6% | 60.1% |
| Avg levels/day | 59.5 | 33.3 |

One-at-a-time sweep of 7 parameters across 82 dates revealed a clean separation: **only price_range, min_spacing, and pivot_len affect which levels exist**. forward_bars, maj_bounce, maj_touches, and touch_zone are pure classification parameters — they shift the solid/dashed rendering but have zero effect on recall or precision.

| Parameter | Effect on support recall |
|---|---|
| price_range | High (+12.7pts at 350 vs 250) |
| min_spacing | High (−46pts at 10.0) — collapses above 4.0 |
| pivot_len | Low (−3.5pts at 10) |
| forward_bars | Zero |
| maj_bounce | Zero |
| maj_touches | Zero |

### 4.2 Phase 2 — 2D Grid Search

price_range × min_spacing grid (5×5 = 25 combos × 82 dates). Best balanced result: price_range=325, min_spacing=3.0 → sup_rec=80.7%, res_rec=46.9%, ~113 levels/day. Going to price_range=350, min_spacing=2.0 gained +3pts recall but produced 175 levels/day — too cluttered. **price_range=325 adopted as production default.**

### 4.3 Phase 3 — Minimum Bounce Floor

Mancini states a level is significant only if price bounced ≥20pts from it. Tested `min_bounce` from 0 to 40 pts. Key finding: at forward_bars=100 (25hr window), ES almost always moves 20pts from any pivot in 25 hours — the filter barely activates. At min_bounce=20 with forward_bars=100, recall dropped only 0.7pts while level count fell 1.3/day. Not worth the complexity; **min_bounce left at 0.0**.

### 4.4 Phase 4 — Short Forward Windows

Tested forward_bars=2–16 (30min–4hr). Two findings: (1) short windows tank recall because pivots haven't bounced 20pts yet in 30–75 min, failing the min_bounce floor entirely; (2) even at 2 bars, major% barely moved — the maj_touches=5 criterion is trivially met from years of price history and dominates classification regardless of bounce window length. Forward_bars and maj_touches cannot be tuned independently.

### 4.5 Phase 5 — 2D Sweep: maj_touches × forward_bars

48 combinations × 215 dates. Recall was dead flat at 80.6% across all 48 combos — confirmed these parameters are pure classification. Mancini's major ratio is consistently ~42%; ours was ~97% at baseline.

Winner: **maj_touches=12, forward_bars=10** → sup_maj%=41.8% (Mancini: 42.1%).

At maj_touches=5 (old default), ~90% of levels were major because years of price history mean almost every zone has been visited 5+ times. At 12, only zones with exceptional historical use qualify via touches alone. The 2.5hr bounce window (forward_bars=10) then becomes a meaningful secondary criterion.

Note: res_maj% at winner combo is 50.6% vs Mancini's 41.4% — structural asymmetry because resistance levels near ATH have fewer historical touches (price hasn't been there before). Accepted limitation.

---

## 5. ML Scoring (Phase 6)

### 5.1 Why ML

After Phase 5, the gap was clear: 80% recall on supports, ~47% on resistances, ~97 extras per day. Parameter tuning had plateaued — the remaining gap reflects Mancini's editorial judgment about which pivots are significant, not any parameter we can tune. ML trained on 216 days of his labels can learn these preferences implicitly.

### 5.2 Phases 6a–6d: Finding the Right Candidate Pool

**Phase 6a (baseline):** Trained XGBoost on ~825 raw candidates/day, 6.8% positive rate. Best F1 at thr=0.50: 27.2%, 181 levels/day. Root cause: precision ceiling ~18% is structural at a 1-in-18 base rate. Touches was the top feature (0.21 importance).

**Phase 6b:** Added sr_flip, price_crossings, round-number features. Round-number features collectively as important as touches. sr_flip weak (0.028) — confirmed-pivot implementation needed. Ceiling unchanged at ~18%.

**Phase 6c:** Tested recency filter (drop pivots >N days old) and significance pre-filter (keep top-N by prominence×bounce). A filter-order bug accidentally inflated results — significance filter was applied globally before price_range, producing only 5–17 candidates/day with misleadingly high F1. Found the bug.

**Phase 6d:** Fixed filter to apply price_range first, then significance. sig_inrange_50 (top 50 in-range pivots): prec=45%, rec=68%, F1=54%. Ceiling broken — but this discards 41% of Mancini's levels that are "modest" pivots. Two paths diverge: match Mancini at the cost of precision, or maximize our own high-confidence system at the cost of coverage.

### 5.3 Phase 6e: ML on the Deduplicated Pool (Final Model)

**Key insight:** `auto_levels.py`'s own dedup step (min_spacing=3.0, newest-first) already reduces 825 raw candidates to ~108/day. Training ML on those 108 raises the base rate from 6.8% to 50.1% — breaking the precision ceiling cleanly, without discarding any Mancini levels.

Pool stats: 108 candidates/day, 54.1 Mancini positives/day (50.1% base rate). Almost all of Mancini's levels survive dedup — the dedup step does the right work; ML just needs to score the 108 and rank them.

**3-fold expanding-window CV results:**

| Threshold | Precision | Recall | F1 | Levels/day |
|---|---|---|---|---|
| 0.30 | 56.8% | 91.8% | 70.2% | 90 |
| 0.40 | 59.3% | 82.4% | 69.0% | 77 |
| 0.50 | 61.8% | 67.0% | 64.1% | 60 |
| 0.60 | 64.6% | 45.4% | 52.4% | 38 |

**Comparison across all phases:**

| Phase | Precision | Recall | F1 | Levels/day |
|---|---|---|---|---|
| 6a baseline (825 cand) | 18.7% | 49.7% | 27.2% | 181 |
| 6d sig_inrange_30 | 50.2% | 63.8% | 56.2% | 32 |
| **6e thr=0.30** | **56.8%** | **91.8%** | **70.2%** | **90** |

**Feature importance (final model):**

| Feature | Importance | Notes |
|---|---|---|
| dist_from_4pm | 0.103 | Distance from current price — top discriminator after dedup |
| sr_flip | 0.078 | S/R role reversal — jumped from 0.028 on raw pool |
| recency_rank | 0.062 | How recent the pivot bar |
| local_density | 0.060 | Cluster density within deduped pool |
| price_crossings | 0.055 | Times price crossed through this level |
| is_mult5 | 0.051 | Multiple of 5 flag |
| dist_d25 | 0.049 | Distance to nearest 25pt multiple |
| bounce | 0.048 | Price rejection magnitude |
| touches | 0.046 | Was #1 at 0.21 on raw pool — all survivors have decent touch counts after dedup |

After dedup, `touches` fell from #1 to #9. What discriminates is *where* the level is and whether it's an S/R flip, not raw touch count.

### 5.4 Integration

The Phase 6e model (`data/phase6e_model.json`) is wired into `backend/auto_levels.py`. Every accepted level carries a `score` field (0–1). `major = score ≥ 0.5` (solid line); below 0.5 is minor (dashed). The `min_score` setting in the Auto Levels tab filters the displayed set client-side — dragging it up trims low-confidence extras in real time without regenerating.

### 5.5 Validation: 4/13/2026 vs Mancini's Published Levels

Anchor: 2026-04-10 4pm ET, close4pm=6855.5.

**Supports (42 Mancini in range, 83 generated):**
- Matched ±2pt: 41/42 = **98%**
- Miss: only 6702.0
- 31 extras are genuine historical pivots; Mancini curates for newsletter clarity
- 29 of Mancini's other supports lie below our ±325pt floor (6273–6527 range)

**Resistances (36 Mancini in range, 44 generated):**
- Matched ±2pt: 24/36 = **67%**
- Miss: 12 levels in the 7048–7139 ATH zone
- The gap is structural: market ran through that zone briefly without forming clean 5-bar swing highs. No parameter or ML change can fix this — the pivots don't exist in the data. Addressed separately (see Section 7).

---

## 6. Score Filter (min_score)

After integration, a `min_score` setting was added to the Auto Levels tab. It filters the already-fetched level set client-side (the `score` field is on every returned level). Default is 0.0 (show all). Setting it to 0.35 trims low-confidence extras while retaining virtually all Mancini-matched levels.

Score distribution at 4/13/2026:
- All 41 matched supports scored 0.22–0.858 (median 0.631)
- Only 2 matched supports below 0.30 — these are the weakest in Mancini's own list
- At thr=0.35: lose 1 Mancini support, remove 12 low-confidence extras

---

## 7. Major/Minor Distinction Study (Phase 7)

With the ML model integrated and performing well on level *selection*, we turned to the question of whether the major/minor classification could be improved — specifically, whether Mancini's own `(major)` labels could be predicted from the features we have.

### 7.1 Data

The 3-class relabeling was: 0 = algo candidate not in Mancini's list, 1 = Mancini minor, 2 = Mancini major. Across 216 days: 4,870 major, 6,823 minor (41.6% major — matching his published ratio closely).

### 7.2 Feature comparison: major vs minor

Mann-Whitney U tests across all features. Only a few were statistically significant:

| Feature | Major | Minor | p-value |
|---|---|---|---|
| dist_d25 | 6.02 | 6.43 | <0.0001 |
| recency_rank | 2248 | 2534 | <0.0001 |
| days_since_pivot | 24.0 days | 27.1 days | <0.0001 |
| pivot_type | 47% highs | 44% highs | 0.0009 |

Notably: **dist_from_4pm is not significant** (p=0.56). Major levels are not closer to the 4pm close than minor ones — confirmed flat across all distance bands (42% major rate from 0–50pts through 200–325pts). A decision tree on Mancini vs minor levels reached only 59.7% accuracy with a 41.6% baseline — barely above guessing.

### 7.3 Recency rule

The most promising signal was recency_rank. Hypothesis: when two levels are near each other, Mancini keeps the more recent one as major. Tested at proximity thresholds D=5 to D=100pts.

Result: at every D, the major is the more recent level only ~52% of the time — essentially a coin flip. The hypothesis does not hold.

### 7.4 Major-major spacing

Visual inspection suggested major levels are always well-spaced from each other. Confirmed in data:
- 93% of adjacent major-major gaps are ≥ 6pts
- 90% are ≥ 8pts (median gap 15pts, mean 16.7pts)
- Minor levels fill the gaps (median gap 11pts, 17% under 6pts)

This is a real structural pattern. However, applying it as a post-processing rule — enforcing minimum major spacing by demoting the lower-scored of a close pair — requires the ML score to reliably discriminate within close pairs. It doesn't: when a Mancini major and minor are within 6–8pts of each other, the major has higher bounce only 49% of the time, higher touches 44% of the time, and is more recent 52% of the time. The score can't pick the right one.

### 7.5 Conclusion

Mancini's major/minor distinction is not reliably learnable from pivot geometry with the features available. The differences between his major and minor levels are real but small across every feature tested. His classification likely reflects holistic judgment — zone significance in context, prior-week price action, structural importance — that can't be reconstructed from a single day's pivot history. The `min_score` filter is the appropriate control: it trims low-confidence levels from the total set, without pretending to replicate a distinction we can't reliably learn.

---

## 8. Remaining Gap: ATH Cluster Detection

The 12 missing resistances in the 7048–7139 zone are a structural problem: market ran through that zone quickly during the late-2025 ATH run without forming the clean 5-bar confirmed swing highs the algorithm requires. Mancini identifies those levels from prior consolidation clusters and channel projections that the pivot detector cannot see.

Proposed fix (task 2): after standard dedup, scan for the top-N highest pivot highs in the lookback window that are not already within 5pts of an accepted level. These represent price clusters that were visited but didn't produce clean confirmed pivots. Details to be designed and tested.

---

## 9. Scripts and Outputs

| File | Purpose |
|---|---|
| `backend/analyze_levels.py` | Phase 1 baseline analysis |
| `backend/sweep_levels.py` | Phase 1 one-at-a-time parameter sweep |
| `backend/analysis_phase2.py` | Phase 2 major/minor study + 2D grid search |
| `backend/analysis_phase3.py` | Phase 3 min_bounce + quality cap |
| `backend/analysis_phase4.py` | Phase 4 short forward window sweep |
| `backend/analysis_phase5.py` | Phase 5 maj_touches × forward_bars grid |
| `backend/analysis_phase6.py` | Phase 6a ML baseline (raw pool) |
| `backend/analysis_phase6b.py` | Phase 6b new features |
| `backend/analysis_phase6c.py` | Phase 6c pool reduction (filter-order bug found) |
| `backend/analysis_phase6d.py` | Phase 6d fixed in-range significance filter |
| `backend/analysis_phase6e.py` | Phase 6e ML on deduped pool — final model |
| `backend/feature_builder.py` | Feature matrix builder (shared by all Phase 6 scripts) |
| `backend/analysis_major_minor.py` | Phase 7a feature comparison, major vs minor |
| `backend/analysis_recency_rule.py` | Phase 7b recency rule + spacing study |
| `data/phase6e_model.json` | Production ML model (XGBoost) |
| `data/auto_levels_analysis.xlsx` | Phase 1–5 results (8 worksheets) |
| `data/major_minor_analysis.xlsx` | Phase 7a results |
| `data/recency_rule_analysis.xlsx` | Phase 7b results |
