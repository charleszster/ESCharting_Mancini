# Auto Level Generator — Parameter Guide

A plain-English reference for what each knob actually does.
Parameters are grouped by what they control, not by name.

---

## Group 1: Which levels exist (affect recall and level count)

These are the only parameters that change *which* levels appear on the chart.
Tuning these trades off recall (catching Mancini's levels) vs. clutter.

### `price_range` (default: 325 pts)
**What it does:** Sets the maximum distance above or below the 4pm close price
that a pivot can be and still generate a level. A pivot 400 pts away is ignored;
a pivot 300 pts away is included.

**Effect:**
- Increase → more levels, higher recall (more of Mancini's distant levels captured)
- Decrease → fewer levels, lower recall

**When to adjust:** If you feel the chart is showing levels too far from current
price that you'll never trade, decrease it. If you're missing levels Mancini draws
in the 300–325pt range, keep it at 325 or increase slightly.

**Research finding:** Best recall at price_range=325. Going to 350 adds a few pct
of recall but inflates level count significantly.

---

### `min_spacing` (default: 3.0 pts)
**What it does:** When two pivot candidates are within this many points of each
other, only the more recent one is kept. This is the primary deduplication knob.

**Effect:**
- Increase → fewer levels (more aggressive merging of nearby pivots), lower recall
- Decrease → more levels (allows tighter clusters), higher recall but more clutter

**When to adjust:** If you see multiple lines crammed within 2–3 pts of each other
that look like the same zone, increase it. If you feel levels are being dropped that
you want to see, decrease carefully.

**Research finding:** Below 2.0 pts, level count explodes with little recall gain.
Above 4.0 pts, recall drops sharply. 3.0 is the sweet spot.

---

### `pivot_len` (default: 5 bars)
**What it does:** How many 15-minute bars on each side of a candle must be lower
(for a pivot high) or higher (for a pivot low) to confirm a pivot. A larger value
means only "sharper" turning points qualify.

**Effect:**
- Increase → fewer pivots detected (only significant swing highs/lows), slightly
  lower recall, cleaner chart
- Decrease → more pivots detected, slightly higher recall, more noise

**When to adjust:** Rarely. The effect on recall is small. Leave at 5 unless you
have a specific reason.

---

## Group 2: Major vs. minor classification (solid vs. dashed lines)

These parameters have **zero effect** on which levels exist or how many appear.
They only control whether each level gets a solid line (major) or dashed line (minor).
You can tune these freely without worrying about losing any levels.

### `maj_touches` (default: 12)
**What it does:** If the number of historical pivot highs and lows within ±2 pts
of a level's price meets or exceeds this count, the level is classified as major.

**Effect:**
- Increase → fewer majors (harder to qualify via touches alone), more minors
- Decrease → more majors (easier to qualify)

**Research finding:** At `maj_touches=5` (old default), ~90% of levels were major
because years of price history mean almost every zone has been visited 5+ times.
At `maj_touches=12`, our major% drops to ~42%, matching Mancini's observed ratio.

---

### `forward_bars` (default: 10 bars = 150 min)
**What it does:** After a pivot forms, this is how many 15-minute bars forward
(in time) the algorithm looks to measure how far price bounced away from the pivot.
A larger bounce → more likely to qualify as major via the bounce criterion.

**Effect:**
- Increase → bounces measured over a longer window (almost always larger), more majors
- Decrease → bounces measured over a shorter window (may not have developed yet), fewer majors

**Interacts with `maj_bounce`:** A level is major if bounce ≥ `maj_bounce` OR
touches ≥ `maj_touches`. With `forward_bars=100` (25 hours), ES almost always
moves 40+ pts from any pivot in that time, so virtually every level qualified via
bounce alone. At `forward_bars=10` (2.5 hours), the bounce window is tighter and
the `maj_touches` criterion carries more weight.

**Research finding:** Tuning `forward_bars` alone won't fix over-classification —
the touch criterion dominates. The two must be tuned together. `forward_bars=10`
paired with `maj_touches=12` produces ~42% major, matching Mancini.

---

### `maj_bounce` (default: 40 pts)
**What it does:** Bounce threshold for the major classification. A level is major
if price moved at least this many points away from the pivot within `forward_bars`
bars after the pivot formed.

**Effect:**
- Increase → fewer majors (higher bar for bounce qualification)
- Decrease → more majors

**Note:** With the current `forward_bars=10` (2.5hr window), this threshold matters
more than it did at `forward_bars=100`. At 10 bars, not all pivots bounce 40pts in
2.5 hours, so the threshold is active. At 100 bars, ES almost always moved 40+pts
in 25 hours, making this criterion nearly always true.

---

### `touch_zone` (default: 2.0 pts)
**What it does:** Radius for counting historical touches. A pivot counts as a
"touch" of a level if it's within this many points of the level's price.

**Effect:**
- Increase → more touches counted per level, more levels reach major threshold
- Decrease → fewer touches counted, fewer majors

**When to adjust:** Rarely. This interacts with `maj_touches`. If you increase
`touch_zone`, you may need to increase `maj_touches` to compensate.

---

## Group 3: Min bounce floor (affects both existence and classification)

### `min_bounce` (default: 0.0 pts)
**What it does:** Hard floor — a pivot must have bounced at least this many points
(within the `forward_bars` window) to be included in the level set at all, regardless
of major/minor status.

**Effect:**
- Increase → fewer levels (weak pivots excluded), higher precision, lower recall
- 0.0 (default) → no exclusion; all pivots within price_range are candidates

**Warning:** Unlike Group 2 parameters, this *does* affect which levels exist, not
just their label. Setting it above 0 reduces recall.

**Research finding (Phase 3):** Mancini states that a level is only significant if
price bounced at least 20pts from it. However, testing at `min_bounce=20` with
`forward_bars=100` showed negligible filtering — ES almost always moves 20pts in
25 hours. At `forward_bars=10`, `min_bounce=20` would be meaningful (2.5hr bounce
window). This interaction has not yet been fully tested. Leave at 0.0 for now.

---

## Quick reference: what to change for common goals

| Goal | Parameter to adjust | Direction |
|---|---|---|
| More levels on chart | `price_range` ↑ or `min_spacing` ↓ | Recall ↑, clutter ↑ |
| Fewer levels on chart | `price_range` ↓ or `min_spacing` ↑ | Recall ↓, cleaner |
| More solid (major) lines | `maj_touches` ↓ or `forward_bars` ↑ | Major% ↑ |
| More dashed (minor) lines | `maj_touches` ↑ or `forward_bars` ↓ | Major% ↓ |
| Sharper pivot detection | `pivot_len` ↑ | Fewer, cleaner pivots |
| Broader pivot detection | `pivot_len` ↓ | More pivots |
| Show only high-conviction | `show_major_only = true` | Minor lines hidden |
| More ATH zone resistances | `ath_cluster_n` ↑ | More supplemental top-N highs |
| Disable ATH cluster | `ath_cluster_n = 0` | No supplemental levels added |

---

## Group 4: ATH cluster detection (supplemental resistances)

### `ath_cluster_n` (default: 15)
**What it does:** After the standard pivot dedup produces `accepted`, scans all
15-min bar highs above `close4pm`, sorted highest-first, and adds up to N
resistance levels that are:
- Not within **5 pts** of any already-accepted level (hardcoded guard)
- Not within **`min_spacing` pts** of each other

These supplemental levels target the ATH zone where strict pivot geometry finds
no clean 5-bar confirmed swing highs — the market ran through those prices quickly
without reversing enough to form a confirmed pivot. ATH cluster levels go through
the same ML scoring as regular levels, so they also respond to `min_score` and
`show_major_only`.

**Effect:**
- Increase → more supplemental resistances added above current price
- 0 → feature disabled entirely

**When to adjust:** If your chart is missing resistance levels in the ATH zone
(prices the market visited but didn't reverse at clearly), increase this. If you
find the ATH zone too cluttered with dashed lines, lower it or raise `min_score`.

**Research finding:** The 12 missing ATH resistances in the 7048–7139 zone
(vs Mancini's 4/13/2026 levels) were the motivation. Standard pivot detection
with N=5 bars finds nothing there; ATH cluster fills the gap.

---

## What does NOT affect which levels appear

- `maj_touches` — classification only
- `forward_bars` — classification only (when `min_bounce=0`)
- `maj_bounce` — classification only (when `min_bounce=0`)
- `touch_zone` — classification only
- `show_major_only` — display filter only (levels still computed, just hidden)

---

## Parameter interactions to watch

**`forward_bars` + `min_bounce`:** If you raise `min_bounce` above 0, the two
parameters become linked — a short `forward_bars` window means fewer pivots will
have bounced enough to clear the floor, reducing recall. Keep `min_bounce=0` unless
you intentionally want to trade recall for precision.

**`maj_touches` + `touch_zone`:** Widening `touch_zone` inflates touch counts,
making it easier to reach the `maj_touches` threshold. If you increase `touch_zone`,
consider increasing `maj_touches` proportionally.

**`price_range` + `min_spacing`:** These jointly determine level count.
A wide `price_range` with tight `min_spacing` produces the most levels;
a narrow `price_range` with wide `min_spacing` produces the fewest. They can
be adjusted in opposite directions to control count independently of coverage.
