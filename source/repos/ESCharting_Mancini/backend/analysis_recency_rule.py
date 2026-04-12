"""
Recency-rule study: when two Mancini levels are within D points of each other,
is the more recent pivot always/usually the major one?

Sweeps D from 5 to 100 pts. For each D, measures:
  - pair_count:       number of (major, minor) pairs within D on the same day
  - recency_correct:  % of pairs where the major is more recent than the minor
  - major_covered:    % of major levels that have at least one minor within D
  - minor_covered:    % of minor levels that have at least one major within D

Also finds the D that maximises recency_correct * major_covered (combined score),
and reports the best simple threshold on days_since_pivot or recency_rank.
"""

import re
import sqlite3
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).parent.parent
MATCH_TOL = 2.0


# ── Parse levels.db ────────────────────────────────────────────────────────────

def _parse_tok(tok):
    tok = tok.strip().strip(',')
    m = re.match(r'^(\d+)-(\d+)$', tok)
    if m:
        a, b = m.group(1), m.group(2)
        b = (a[:len(a)-len(b)] + b) if len(b) < len(a) else b
        return (float(a) + float(b)) / 2
    return float(tok)

def _parse_man_with_major(text):
    if not text:
        return []
    out = []
    for tok in re.split(r',\s*', text.strip()):
        tok = tok.strip()
        if not tok:
            continue
        is_major = bool(re.search(r'\(major\)', tok, re.IGNORECASE))
        clean = re.sub(r'\s*\(major\)', '', tok, flags=re.IGNORECASE).strip()
        if clean:
            try:
                out.append((_parse_tok(clean), is_major))
            except Exception:
                pass
    return out

def load_mancini_with_major():
    conn = sqlite3.connect(ROOT / 'data' / 'levels.db')
    rows = conn.execute(
        "SELECT trading_date, supports, resistances FROM levels "
        "WHERE trading_date >= '2025-03-07' ORDER BY trading_date"
    ).fetchall()
    conn.close()
    return {td: _parse_man_with_major(s) + _parse_man_with_major(r)
            for td, s, r in rows}


# ── Build matched dataset ──────────────────────────────────────────────────────
# For each Mancini level (major or minor), find its matched candidate in
# phase6e_features and pull recency_rank + days_since_pivot.

def build_matched(df_feat, man_by_date):
    """
    Returns a DataFrame with one row per matched Mancini level:
      trading_date, price, is_major, recency_rank, days_since_pivot
    """
    dates_arr  = df_feat['trading_date'].values
    prices_arr = df_feat['price_rounded'].values
    recency_arr = df_feat['recency_rank'].values
    days_arr    = df_feat['days_since_pivot'].values

    rows = []
    for td, man_levels in man_by_date.items():
        day_idx = np.where(dates_arr == td)[0]
        if len(day_idx) == 0:
            continue
        day_prices   = prices_arr[day_idx]
        day_recency  = recency_arr[day_idx]
        day_days     = days_arr[day_idx]

        for price, is_major in man_levels:
            dists = np.abs(day_prices - price)
            best  = dists.argmin()
            if dists[best] <= MATCH_TOL:
                rows.append({
                    'trading_date':    td,
                    'price':           float(day_prices[best]),
                    'is_major':        int(is_major),
                    'recency_rank':    int(day_recency[best]),
                    'days_since_pivot': int(day_days[best]),
                })

    return pd.DataFrame(rows)


# ── Sweep distance thresholds ──────────────────────────────────────────────────

def sweep_distance(matched, d_values):
    """
    For each distance D, find all (major, minor) pairs on the same day within D pts.
    Measure whether the major is more recent (lower recency_rank).
    """
    results = []

    dates = matched['trading_date'].unique()
    majors = matched[matched.is_major == 1]
    minors = matched[matched.is_major == 0]

    n_total_major = len(majors)
    n_total_minor = len(minors)

    for D in d_values:
        pair_count       = 0
        recency_correct  = 0   # major more recent than minor
        recency_tie      = 0
        major_covered_set = set()
        minor_covered_set = set()

        for td in dates:
            day_maj = majors[majors.trading_date == td]
            day_min = minors[minors.trading_date == td]
            if day_maj.empty or day_min.empty:
                continue

            maj_prices = day_maj['price'].values
            min_prices = day_min['price'].values
            maj_rec    = day_maj['recency_rank'].values
            min_rec    = day_min['recency_rank'].values

            for mi, (mp, mr) in enumerate(zip(maj_prices, maj_rec)):
                dists = np.abs(min_prices - mp)
                near  = np.where(dists <= D)[0]
                if len(near) == 0:
                    continue

                major_covered_set.add((td, mp))

                for ni in near:
                    minor_covered_set.add((td, min_prices[ni]))
                    pair_count += 1
                    if mr < min_rec[ni]:         # lower rank = more recent
                        recency_correct += 1
                    elif mr == min_rec[ni]:
                        recency_tie += 1

        pct_correct = recency_correct / pair_count * 100 if pair_count else 0
        pct_covered_maj = len(major_covered_set) / n_total_major * 100
        pct_covered_min = len(minor_covered_set) / n_total_minor * 100
        combined = pct_correct * pct_covered_maj / 100   # harmonic-ish score

        results.append({
            'D':               D,
            'pair_count':      pair_count,
            'recency_correct%': round(pct_correct, 1),
            'major_covered%':  round(pct_covered_maj, 1),
            'minor_covered%':  round(pct_covered_min, 1),
            'combined_score':  round(combined, 1),
        })

    return pd.DataFrame(results)


# ── Days-since-pivot threshold sweep ─────────────────────────────────────────
# Separately: ignoring pairing, just ask "if we label as major any level
# with days_since_pivot <= T, how well does that match Mancini's major labels?"

def sweep_days_threshold(matched, t_values):
    """Simple threshold sweep on days_since_pivot."""
    y = matched['is_major'].values
    days = matched['days_since_pivot'].values
    results = []
    for T in t_values:
        pred = (days <= T).astype(int)
        tp = ((pred == 1) & (y == 1)).sum()
        fp = ((pred == 1) & (y == 0)).sum()
        fn = ((pred == 0) & (y == 1)).sum()
        tn = ((pred == 0) & (y == 0)).sum()
        prec    = tp / (tp + fp) if (tp + fp) else 0
        recall  = tp / (tp + fn) if (tp + fn) else 0
        f1      = 2 * prec * recall / (prec + recall) if (prec + recall) else 0
        acc     = (tp + tn) / len(y)
        results.append({
            'days_threshold': T,
            'precision':      round(prec,   3),
            'recall':         round(recall, 3),
            'f1':             round(f1,     3),
            'accuracy':       round(acc,    3),
        })
    return pd.DataFrame(results)


# ── Main ───────────────────────────────────────────────────────────────────────

print("Loading feature matrix...")
df_feat = pd.read_parquet(ROOT / 'data' / 'phase6e_features.parquet')

print("Loading Mancini levels...")
man_by_date = load_mancini_with_major()

print("Building matched dataset...")
matched = build_matched(df_feat, man_by_date)
n_maj = matched.is_major.sum()
n_min = (matched.is_major == 0).sum()
print(f"  Matched: {n_maj} major, {n_min} minor across "
      f"{matched.trading_date.nunique()} dates")

# Days-since-pivot stats by class
print("\ndays_since_pivot by class:")
for cls, name in [(1, 'major'), (0, 'minor')]:
    vals = matched[matched.is_major == cls]['days_since_pivot']
    print(f"  {name}: mean={vals.mean():.1f}  median={vals.median():.0f}  "
          f"p25={vals.quantile(0.25):.0f}  p75={vals.quantile(0.75):.0f}")

print("\nrecency_rank by class:")
for cls, name in [(1, 'major'), (0, 'minor')]:
    vals = matched[matched.is_major == cls]['recency_rank']
    print(f"  {name}: mean={vals.mean():.0f}  median={vals.median():.0f}  "
          f"p25={vals.quantile(0.25):.0f}  p75={vals.quantile(0.75):.0f}")

# Distance sweep
print("\n" + "="*70)
print("DISTANCE SWEEP: recency rule accuracy at each proximity threshold")
print("="*70)
d_values = list(range(5, 55, 5)) + [60, 70, 80, 100]
dist_results = sweep_distance(matched, d_values)
print(dist_results.to_string(index=False))

best_row = dist_results.loc[dist_results['combined_score'].idxmax()]
print(f"\nBest D by combined score: {best_row['D']} pts  "
      f"({best_row['recency_correct%']}% recency-correct, "
      f"{best_row['major_covered%']}% major covered)")

# Days-since-pivot threshold sweep
print("\n" + "="*70)
print("DAYS-SINCE-PIVOT THRESHOLD: standalone major/minor prediction")
print("="*70)
t_values = list(range(1, 31)) + [35, 40, 50, 60, 90, 120, 180]
days_results = sweep_days_threshold(matched, t_values)
best_f1_row = days_results.loc[days_results['f1'].idxmax()]
print(days_results.to_string(index=False))
print(f"\nBest threshold by F1: days_since_pivot <= {best_f1_row['days_threshold']}  "
      f"(F1={best_f1_row['f1']:.3f}, "
      f"precision={best_f1_row['precision']:.3f}, "
      f"recall={best_f1_row['recall']:.3f})")

# Save
OUT_PATH = ROOT / 'data' / 'recency_rule_analysis.xlsx'
with pd.ExcelWriter(OUT_PATH, engine='openpyxl') as writer:
    dist_results.to_excel(writer, sheet_name='Distance Sweep', index=False)
    days_results.to_excel(writer, sheet_name='Days Threshold Sweep', index=False)
    matched.to_excel(writer, sheet_name='Matched Levels', index=False)

print(f"\nSaved: {OUT_PATH}")
