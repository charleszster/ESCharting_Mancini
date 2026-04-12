# ES Level Edge Study — Design Document

**Goal:** Find statistically significant combinations of features that predict
favorable price movement after a level touch. The aim is a discretionary
checklist: when N of M conditions are present, take the trade with confidence.

---

## 1. Core Premise

Auto levels already exist. The question is not "are these good levels?" (we
measured that vs Mancini — 98% recall on supports). The question is:

> **When price touches one of these levels, what predicts whether it bounces?**

---

## 2. What Constitutes a "Touch"

- A **touch episode** begins when any 1-min bar's low (for support) or high
  (for resistance) comes within `TOUCH_ZONE` (2.0 pts) of a level price.
- Consecutive bars within `TOUCH_ZONE` are grouped into one episode (not
  counted separately).
- A new episode of the same level begins only after `TOUCH_COOLDOWN` (15 bars
  = 15 min) of price being outside `TOUCH_ZONE`.
- The episode's **reference bar** is the first bar of the episode — this is
  the hypothetical entry bar.

---

## 3. Levels Used

For each trading day D:
- Levels are computed with anchor = most recent 4pm ET close on or before D-1
- Production defaults: pivot_len=5, price_range=325, min_spacing=3.0,
  touch_zone=2.0, ath_cluster_n=15, ML scoring enabled

Levels computed once per anchor date. Touch detection runs on 1-min bars for
the full 24hr session following the anchor (4pm D-1 to 4pm D).

RTH (09:30–16:00 ET) vs. ETH is captured as a feature, not a filter — we may
find RTH touches behave very differently from ETH touches.

---

## 4. Features

### 4a. Level features (computed by auto_levels.py)

| Feature | Description |
|---|---|
| `level_price` | Level price (pts) |
| `is_support` | True = support, False = resistance |
| `ml_score` | Phase 6e XGBoost score 0–1 |
| `is_major` | ml_score ≥ 0.5 |
| `sr_flip` | Level was previously the opposite role (S/R flip) |
| `dist_from_4pm` | Distance from anchor close4pm (pts) |
| `historical_touches` | Count of prior pivots within ±2pts |
| `days_since_pivot` | Age of the forming pivot |
| `recency_rank` | Bars since pivot (newer = lower rank) |
| `local_density` | Other accepted levels within ±10pts |
| `is_mult5` | Level price is a multiple of 5 |
| `dist_round` | Distance to nearest 25pt round number |
| `historical_bounce` | How far price bounced from the pivot originally |
| `price_crossings` | Times price crossed through this level historically |
| `is_ath_cluster` | True if level came from ATH cluster (not standard pivot) |

### 4b. Context features (new — computed at touch time)

| Feature | Description |
|---|---|
| `touch_n_today` | How many prior touch episodes of THIS level occurred today (0 = first touch) |
| `approach_vel` | Price change per bar over last 20 1-min bars before touch (pts/bar). Negative = falling into support. |
| `approach_bars` | How many 1-min bars price took to travel from 20pts away to within touch zone |
| `time_of_day_mins` | Minutes since 00:00 ET. 570 = 09:30 open, 960 = 16:00 close |
| `is_rth` | True if touch is in 09:30–16:00 ET window |
| `trend_dir_60` | Sign of (close[now] - close[60 bars ago]) — trend direction over last 60 min |
| `trend_strength_60` | Abs(close[now] - close[60 bars ago]) — trend magnitude over last 60 min (pts) |
| `trend_dir_240` | Same over last 240 min (4 hours) |
| `trend_strength_240` | Same over last 240 min |
| `vol_zscore_touch` | Volume z-score of the touch bar vs. 20-bar rolling mean |
| `vol_zscore_approach` | Mean volume z-score of last 20 bars approaching level |
| `vol_drying` | True if last 5 bars had declining volume (volume contraction into level) |
| `atr_20` | Average true range of last 20 1-min bars (local volatility) |
| `day_range_pct` | How much of the day's range has already been covered (touch bar high-low / prior ATR estimate). Proxy for "how extended is the move already". |

### 4c. Session context (day-level features)

| Feature | Description |
|---|---|
| `day_open` | First 1-min bar open of RTH session |
| `dist_from_open` | Level price distance from day open (pts) |
| `gap_pts` | Overnight gap vs. prior close (pts) — positive = gap up |

---

## 5. Outcome Labels

Measured from the reference bar (episode start) using 1-min high/low/close.

### Directional convention
- **Support**: favorable = UP (price moves away from level upward)
- **Resistance**: favorable = DOWN (price moves away from level downward)

### Continuous outcomes (at 4 windows: 10, 30, 60, 120 min)
- `max_fav_N` — maximum favorable excursion in N bars (using high for long, low for short)
- `max_adv_N` — maximum adverse excursion in N bars (using low for long, high for short)

### Binary outcomes (2:1 R:R: target 10pts, stop 5pts)
- `win_10`, `win_30`, `win_60`, `win_120` — did price reach +10pts favorable
  before −5pts adverse in that time window?

### Failed breakdown / failed breakout labels (support only)
- `broke_below` — True if any bar in the next 10 bars closed below the level
- `reclaimed_after_break` — True if broke_below AND price closed back above
  within the next 30 bars (classic failed breakdown pattern)

### Bars to outcome
- `bars_to_target_30` — how many bars until +10pts favorable (within 30-bar window), NaN if not reached
- `bars_to_stop_30` — how many bars until -5pts adverse (within 30-bar window), NaN if not reached

---

## 6. Study Window

- Full data range: 2016-03-29 to 2026-03-25 (~10 years, ~2,500 trading days)
- Expected touch events: ~50 levels/day × ~2 touches/day on average × 2,500 days ≈ **250,000 touch events**

250K events is comfortably within local XGBoost capacity. No cloud needed unless
we want GPU-accelerated deep learning (not needed for tabular data).

---

## 7. Analysis Plan (Phase 2 — after dataset is built)

### 7a. Univariate screening
For each feature, split touch events into bins and compare `win_30` rate.
Identify which individual features have the strongest signal.

### 7b. Feature interaction study
For the top features, examine 2-way combinations:
- e.g., "ml_score ≥ 0.5 AND touch_n_today == 0 AND vol_drying == True"
- Goal: find the specific conditions that push win rate to 60%+

### 7c. ML model (XGBoost on touch events)
Train XGBoost to predict `win_30` from all features.
This surfaces non-obvious interactions that univariate analysis misses.

### 7d. Long vs. short breakdown
Separate support touches (long setups) from resistance touches (short setups).
ES upward bias likely shows up here clearly.

### 7e. Failed breakdown study
Of all support touches, what % turn into failed breakdowns?
When a failed breakdown occurs, what was different about those setups?

### 7f. Checklist construction
Translate findings into a ranked checklist:
- Each condition = 1 point
- Score 0–N at any given touch
- Win rate curve by score → pick the minimum score threshold for "take the trade"

---

## 8. Key Hypotheses to Test

1. **First touch beats subsequent touches** — touch_n_today == 0 should have higher win rate
2. **Slow approach beats fast** — lower abs(approach_vel) → price is drifting in, not running; more likely to hold
3. **Volume drying up at touch** — vol_drying == True is a classic institutional accumulation signal
4. **RTH outperforms ETH** — more participants, more respect for levels
5. **SR flip levels outperform** — sr_flip == True should be the single strongest binary feature
6. **Round numbers add edge** — is_mult5 == True should add ~5pts to win rate
7. **High ML score matters** — but it measures "Mancini would draw this", not "this will bounce"; these may diverge

---

## 9. Scripts

| File | Purpose |
|---|---|
| `build_dataset.py` | Iterates all trading days, computes levels, finds touches, extracts features, labels outcomes → `data/touch_events.parquet` |
| `analyze_outcomes.py` | Univariate analysis, feature importance, win rate curves |
| `analyze_combinations.py` | 2-way/3-way feature interaction study |
| `analyze_failed_breakdowns.py` | Failed breakdown / failed breakout deep dive |
| `build_checklist.py` | Translates findings into a scored checklist |

---

## 10. Parameters (adjustable)

| Parameter | Default | Notes |
|---|---|---|
| TOUCH_ZONE | 2.0 pts | How close = "touch" |
| TOUCH_COOLDOWN | 15 bars | Min gap between touch episodes of same level |
| TARGET_PTS | 10.0 pts | Favorable threshold for binary outcome |
| STOP_PTS | 5.0 pts | Adverse threshold for binary outcome |
| APPROACH_LOOKBACK | 20 bars | Bars to measure approach velocity |
| TREND_LOOKBACK_SHORT | 60 bars | Bars for short-term trend context |
| TREND_LOOKBACK_LONG | 240 bars | Bars for long-term trend context |
| VOL_LOOKBACK | 20 bars | Bars for volume z-score baseline |
