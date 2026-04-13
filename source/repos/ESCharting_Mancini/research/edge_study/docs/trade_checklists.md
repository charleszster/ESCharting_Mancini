# ES Futures — Level Trade Checklists

> Based on 95,799 touch events, 2016–2026 (10-year study)
> Outcome: win_30 = price hits +10pts target before -5pts stop within 30 min
> Baseline win rate: 31.0% | Breakeven (2:1 R:R): 33.3%

---

## Setup A — Failed Breakdown (FB)

**Concept:** A support level breaks below during RTH, then reclaims.
The break is a trap. You enter on the reclaim.

**Win rate:** 75–86% reclaim rate depending on conditions
(Not a 2:1 win rate — this measures whether the level reclaims at all,
not how far it runs. Manage accordingly.)

### Mandatory conditions (skip the trade if either fails)

- [ ] RTH session only (09:30–16:00 ET)
      *ETH breaks reclaim only 61% of the time — not tradeable*
- [ ] Price has closed a 1-min bar **below** the support level

### Entry trigger

- [ ] First 1-min bar to **close back above** the level
      *This is the entry bar. Not a touch — a confirmed reclaim close.*

### Stop

- [ ] Below the low of the breakdown bar (the bar that closed below)
      *Typically 3–6 pts depending on volatility*

### Target

- [ ] +10 pts from entry (first partial)
      *Or use the next resistance level above as a guide*

### Score — additional conditions (more = better)

| Condition | Notes |
|---|---|
| Afternoon (14:30–16:00 ET) | Reclaim rate jumps to **86%** vs 73% morning |
| Opening (09:30–10:00 ET) | Second-best window; break rate high, reclaim 75% |
| Low volume on breakdown bar | Low vol z-score = not a conviction break |
| Level close to prior 4pm close (<25 pts) | Nearby levels reclaim more reliably |
| First touch of this level today | Untested levels > worn-down levels |

> [!warning] Avoid
> - Breaks during 08:30–09:30 ET (economic reports) — only 62% reclaim
> - ETH breaks entirely
> - High-volume breakdown bars (vol z-score > 6) — those tend to follow through

---

## Setup B — Afternoon First Touch (15:30 Window)

**Concept:** A level that has not been touched all day gets tested
for the first time in the last 30 minutes of RTH.
The level has been respected all day. Institutional close positioning makes it sticky.

**Win rate:** 57.6% baseline | 65% with slow approach | 62% with SR flip + slow

### Mandatory conditions (skip the trade if either fails)

- [ ] **15:30–16:00 ET only**
      *14:30–15:30 has no edge (28–29% win rate — below breakeven)*
- [ ] **First touch of this level today** (touch_n_today = 0)
      *Repeat touches drop to 30.2% — skip them entirely*

### Entry

- [ ] At the touch of the level
      *Support: 1-min bar low within 2 pts | Resistance: high within 2 pts*
- [ ] Stop: 5 pts against the level
- [ ] Target: 10 pts favorable

### Score — additional conditions (more = better)

| Condition | Win rate boost | Notes |
|---|---|---|
| Level within 25 pts of prior 4pm close | +6% | Far levels (>75 pts) have no edge |
| Approach: drifting or counter-retest | +14–17% | Slow vel (-0.2 to +0.2 pts/bar) |
| SR flip level | +8% | Previously the opposite role |
| ML major (score >= 0.5) | +2% | Minor incremental boost |
| Round number (multiple of 5) | +1% | Minor |

> [!tip] Best combined setup
> First touch + 15:30 window + slow/drifting approach + within 25 pts of anchor
> Historical win rate: ~65% (n=~500+ events)

> [!warning] Avoid
> - Any level touched earlier today
> - Levels hit before 15:30 (even if in RTH afternoon)
> - Fast/running approach into the level (vel > 0.5 pts/bar)
> - Levels far from the anchor (>75 pts away)

---

## Morning exception — Opening FB only (09:30–10:00 ET)

**This is the only morning setup with data support.**

- [ ] Support level breaks in the first 30 min of RTH
- [ ] 1-min bar closes back above the level
- [ ] Stop below breakdown bar low
- [ ] Skip if break occurred on a news spike (08:30–09:30 data)
- [ ] 75% reclaim rate — weaker than afternoon FB but real

> [!note]
> No initial-touch edge exists in the morning session at any time slot.
> All morning touch win rates: 26–32% (at or below breakeven).
> The morning FB at the open is the only exception.

---

## Quick reference

| Setup | Time window | Win rate | Frequency |
|---|---|---|---|
| FB — Afternoon | 14:30–16:00 | 86% reclaim | ~1–2/week |
| FB — Opening | 09:30–10:00 | 75% reclaim | ~1–2/week |
| First Touch | 15:30–16:00 | 57–65% | ~1–2/week |
| Any morning touch | 07:30–10:30 | 26–32% | skip |
