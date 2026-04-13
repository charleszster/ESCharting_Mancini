# ES Futures Level Touch — Edge Study Report

**Study period:** March 2016 – March 2026 (10 years)
**Dataset:** 95,799 touch events across 2,501 trading days
**Outcome metric:** win_30 — price hits +10 pts target before −5 pts stop within 30 min (2:1 R:R)
**Breakeven win rate:** 33.3%
**Baseline win rate (all touches, no filter):** 31.0%

---

## 1. Study Design

### What a "touch event" is

A touch episode begins when any 1-min bar's low (for support) or high (for resistance) comes within 2.0 pts of a level. Consecutive bars within the zone are grouped into one episode. A new episode of the same level begins only after 15 bars (15 min) of price being outside the zone.

Each touch event records:
- All level features (ML score, SR flip, distance from anchor, historical touches, etc.)
- Context at the moment of touch (approach velocity, volume, time of day, trend direction/strength)
- Binary win/loss outcome at 4 windows: 10, 30, 60, and 120 min
- Failed breakdown label: whether the level broke below and then reclaimed

### Levels used

Levels are the full auto-generated set from `auto_levels.py`: every pivot passing deduplication and ML scoring, including ATH cluster levels. Roughly 50–70 levels per anchor date. **Mancini draws ~10–15 levels by hand and trades a fraction of those.** All win rates in this study are therefore conservative — a more selective level filter would push win rates higher.

### What "anchor price" means

The prior trading day's 4:00 PM ET close (the 15-min bar closing at exactly 4pm). All level classifications (support vs. resistance) and distance measurements reference this price.

---

## 2. Key Findings

### 2a. What doesn't work

- **Morning initial touches (7:30–11:30 ET): 26–32% win rate** — at or below breakeven at every time slot. The morning session is where levels get probed and broken as price discovers the day's range. Fading a level touch at face value in the morning is fighting that discovery process.
- **Repeat touches (2nd+ touch of a level today): 30.2%** — once a level has been tested, the edge is largely gone. Don't trade the 2nd visit.
- **ETH session: 25%** — well below breakeven. Skip ETH level touches entirely.
- **High ML score levels (0.8–1.0): 26.5%** — the most prominent Mancini levels actually trade *worse*. They attract too much traffic and get faded. The ML score predicts "Mancini would draw this," not "this will bounce."

### 2b. The single most important variable: time of day

| Time slot | Win rate | n |
|---|---|---|
| Pre-market (00:00–09:30) | 24.8% | 13,224 |
| Morning 1 (09:30–11:00) | 31.2% | 9,894 |
| Morning 2 (11:00–12:30) | 30.5% | 5,280 |
| Midday (12:30–14:30) | 29.4% | 6,236 |
| **Afternoon (14:30–16:00)** | **44.8%** | **9,983** |
| After-hours (16:00–24:00) | 25.3% | 7,938 |

**Within the afternoon, the edge is concentrated in the last 30 minutes:**

| Time slot | Win rate | n |
|---|---|---|
| 14:30–15:00 | 28.9% | 1,797 |
| 15:00–15:30 | 29.4% | 1,873 |
| **15:30–16:00** | **53.9%** | **6,313** |

The 14:30–15:30 window has no edge at all (below breakeven). The 15:30–16:00 window is where institutional close positioning concentrates order flow at levels.

### 2c. The most important features (XGBoost feature importance)

| Feature | Importance |
|---|---|
| atr_20 (local volatility) | 12.1% |
| is_rth (RTH session) | 11.2% |
| time_of_day_mins | 10.8% |
| dist_from_4pm (distance from anchor) | 6.1% |
| approach_vel | 4.6% |
| touch_n_today | 4.6% |
| approach_bars | 4.5% |
| trend_strength_60 | 4.2% |
| ml_score | 1.9% |

ML score ranks near the bottom. Volatility regime, time of day, and distance from the anchor dominate.

### 2d. Approach velocity

For **supports** in the afternoon:

| Approach | Win rate |
|---|---|
| Running fast down (vel < −0.5) | 36.6% |
| Fast (−0.5 to −0.2) | 39.1% |
| Slow (−0.2 to −0.05) | 46.3% |
| **Drifting (−0.05 to +0.05)** | **58.9%** |
| **Counter-trend retest (rising into support)** | **61.6%** |

A fast move *into* support in the afternoon is the weakest setup. A slow drift or counter-trend retest is the strongest — price approaching from below (already bounced) or barely moving.

### 2e. Failed breakdown statistics

Of all support touches across 10 years:
- 29.2% break below the level
- **70.8% of those breaks reclaim** (failed breakdown rate = 20.7% of all support touches)

By session:

| Session | Break rate | Reclaim rate | FB rate |
|---|---|---|---|
| **Afternoon (14:30–16:00)** | 37.6% | **86.1%** | 32.4% |
| Morning 1 (09:30–11:00) | 42.3% | 73.2% | 31.0% |
| Midday | 32.6% | 72.3% | 23.5% |
| After-hours | 22.7% | 54.9% | 12.5% |

**Afternoon breaks reclaim at nearly 90%.** ETH breaks only reclaim 55–65% of the time.

What predicts a genuine breakdown (does NOT reclaim):
- ETH session: 61% reclaim vs 77% RTH — biggest differentiator
- High volume on the breakdown bar: reclaimed=5.6 z-score vs stayed broken=8.1 z-score
- is_rth was the #1 XGBoost feature for predicting reclaim (19.1% importance)

---

## 3. Recommended Setups

### Setup A — Failed Breakdown (FB)

**Premise:** A support level that breaks during RTH reclaims 70–86% of the time. The break is a trap.

**Entry:** First 1-min bar that closes back above the level after having closed below it.

**Stop:** Below the low of the breakdown bar (~3–6 pts depending on ATR).

**Target:** +10 pts from entry (or next resistance).

**Filter checklist:**
- RTH session (mandatory — skip all ETH breaks)
- Afternoon (14:30–16:00): reclaim rate 86% vs 73% morning
- Low volume on the breakdown bar (low z-score = not a conviction move)
- First touch of the level today before the break
- Level within 25 pts of anchor price

**Year-by-year consistency (2024–2026):**

| Year | Reclaim rate | Wins | Losses | Net pts (1 ES) |
|---|---|---|---|---|
| 2024 | 89.2% | 214 | 26 | +1,870 pts |
| 2025 | 88.6% | 472 | 61 | +4,110 pts |
| 2026 (partial) | 85.9% | 122 | 20 | +1,120 pts |

---

### Setup B — Afternoon First Touch (15:30 Window)

**Premise:** A level untouched all day that price reaches in the last 30 min of RTH. Institutional close positioning makes these levels sticky.

**Entry:** At the touch of the level. Support: 1-min bar low within 2 pts. Resistance: high within 2 pts.

**Stop:** 5 pts against the level.

**Target:** 10 pts favorable.

**Filter checklist:**
- 15:30–16:00 ET window (mandatory — 14:30–15:30 has no edge)
- First touch of this level today (mandatory — repeat touches = 30.2%)
- Level within 25 pts of anchor price (+6% vs far levels)
- Slow/drifting or counter-trend approach (+14–17%)
- SR flip level (+8%)
- ML major (+2%)

**Best combinations (afternoon window):**

| Combo | Win rate | n (10yr) |
|---|---|---|
| First touch + slow approach (supports) | 65.1% | 545 |
| First touch + slow/drift + SR flip | 61.6% | 1,467 |
| First touch + slow approach (resistances) | 59.8% | 533 |
| First touch + 15:30 window | 57.6% | 5,441 |
| First touch + SR flip + Major | 55.1% | 3,959 |

**Year-by-year consistency (afternoon first touch, win_30):**

| Year | Win rate | n |
|---|---|---|
| 2018 | 37.4% | 714 |
| 2019 | 34.7% | 262 |
| 2020 | 47.0% | 1,640 |
| 2021 | 51.7% | 802 |
| 2022 | 43.0% | 2,287 |
| 2023 | 42.4% | 982 |
| 2024 | 48.3% | 1,053 |
| 2025 | 46.9% | 1,713 |
| 2026 (partial) | 44.9% | 463 |

Consistent positive edge from 2018 onward. 2016–2017 are anomalous (very few touch events — likely a data artifact).

---

### Morning exception — Opening FB (09:30–10:00)

The one morning setup with data support. The first 30 min of RTH has the highest break rate (45.2%) with 75% reclaim — classic false break at the open.

**Entry:** First 1-min close back above the level after a break.
**Stop:** Below breakdown bar low.
**Avoid:** Breaks during 08:30–09:30 (economic reports — only 62% reclaim).

---

## 4. Hypothetical P&L — Last 2 Years (Apr 2024 – Apr 2026)

**Assumptions:**
- 1 contract per trade, every qualifying setup taken mechanically
- +10 pts target / −5 pts stop (as defined in the study)
- No commissions, no slippage, no position management
- Setup B uses win_30 (measured from touch bar = actual entry)
- Setup A uses reclaim/non-reclaim as win/loss proxy

> **Critical caveat:** Setup B fires 4.59 times per day because the study uses all auto-generated levels (~50–70/day). A trader applying judgment to select levels (as Mancini does) would take ~1–2 Setup B trades per day at most. The raw numbers below represent a mechanical upper bound, not a realistic trading plan. Setup A is more realistic at ~1.9/day.

### Setup B — Afternoon First Touch (all auto-levels, 1 MES contract)

| Year | Win rate | Wins | Losses | Net pts | Net $ MES |
|---|---|---|---|---|---|
| 2024 | 54.4% | 286 | 240 | +1,660 | +$8,300 |
| 2025 | 59.8% | 599 | 403 | +3,975 | +$19,875 |
| 2026 (partial) | 55.3% | 141 | 114 | +840 | +$4,200 |
| **2-yr total** | **57.5%** | **1,026** | **757** | **+6,475** | **+$32,375** |

### Setup A — Afternoon FB (all auto-levels, 1 MES contract)

| Year | Reclaim rate | Wins | Losses | Net pts | Net $ MES |
|---|---|---|---|---|---|
| 2024 | 89.2% | 214 | 26 | +2,010 | +$10,050 |
| 2025 | 88.6% | 472 | 61 | +4,415 | +$22,075 |
| 2026 (partial) | 85.9% | 122 | 20 | +1,120 | +$5,600 |
| **2-yr total** | **88.3%** | **808** | **107** | **+7,545** | **+$37,725** |

### Setup A — Opening FB (1 MES contract)

| Period | Reclaim rate | Wins | Losses | Net pts | Net $ MES |
|---|---|---|---|---|---|
| 2-yr total | 75.7% | 305 | 98 | +2,560 | +$12,800 |

### Combined (all 3 setups, 1 MES contract each)

| | Net pts | Net $ MES | Net $ ES |
|---|---|---|---|
| 2-yr total | +16,580 | +$82,900 | +$829,000 |

---

## 5. Important Caveats

1. **Level selectivity:** These results are on all auto-generated levels. Mancini draws a curated subset. Applying his level selection would reduce trade frequency but likely increase win rates beyond what's shown here.

2. **Entry quality:** The study enters mechanically at the first bar touching within 2 pts. A human trader waits for a specific candle — rejection wick, inside bar, high-volume reversal. Better entry timing would improve effective R:R.

3. **No position management:** The study uses fixed 10 pt target / 5 pt stop with no partial exits or stop-to-breakeven adjustments. Active management would change outcomes significantly.

4. **Slippage and commissions:** ES/MES futures are highly liquid; slippage on a market order is typically 0.25–0.5 pts. At 10 pt targets this is minor but non-zero.

5. **Setup B frequency:** 4.59 setups/day is misleading. It includes every auto-level touched in the 15:30 window — many of which a trader would not take. Realistic frequency after level selection: 1–2/day.

6. **The ML score finding:** Higher-scored levels (the "obvious" Mancini-quality levels) trade worse because they're more trafficked. This is worth keeping in mind when selecting setups — the cleaner-looking levels may not be the best trades.

---

## 6. Next Steps

- [ ] Add price action features (rejection wick size, inside bar) to the dataset — likely the single biggest improvement
- [ ] Test whether restricting to only SR flip levels changes the P&L materially
- [ ] Study the losing afternoon FB trades (the 12–14% that don't reclaim) — is there a reliable exit signal?
- [ ] Consider a morning-session extension: does the opening FB at a level that's also an SR flip and close to anchor perform better than the 75% baseline?
