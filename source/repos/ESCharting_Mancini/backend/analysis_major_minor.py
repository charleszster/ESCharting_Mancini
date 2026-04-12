"""
Phase 7a: Statistical analysis of Mancini major vs minor levels.

Goal: understand what features distinguish levels Mancini marks as (major)
from those he leaves unmarked (minor), using 216 days of history in levels.db.

Labels:
  0 = algo candidate not in Mancini's list
  1 = Mancini minor (in his list, no (major) tag)
  2 = Mancini major (in his list, with (major) tag)

Outputs results to stdout and saves to data/major_minor_analysis.xlsx.
"""

import re
import sqlite3
import numpy as np
import pandas as pd
from pathlib import Path
from scipy import stats

ROOT = Path(__file__).parent.parent
MATCH_TOL = 2.0

FEATURE_COLS = [
    'pivot_type', 'is_support',
    'bounce', 'touches', 'local_density', 'prominence',
    'vol_zscore', 'consolidation', 'clean_departure',
    'sr_flip', 'price_crossings',
    'dist_from_4pm', 'dist_d5', 'dist_d25', 'dist_d50', 'dist_d100',
    'is_mult5', 'dist_round_to_mult5',
    'days_since_pivot', 'recency_rank',
]

# ── Parse Mancini levels preserving major/minor ────────────────────────────────

def _parse_tok(tok):
    tok = tok.strip().strip(',')
    m = re.match(r'^(\d+)-(\d+)$', tok)
    if m:
        a, b = m.group(1), m.group(2)
        b = (a[:len(a)-len(b)] + b) if len(b) < len(a) else b
        return (float(a) + float(b)) / 2
    return float(tok)

def _parse_man_with_major(text):
    """Return list of (price, is_major) tuples."""
    if not text:
        return []
    out = []
    # Split on commas but keep (major) attached to preceding token
    # Pattern: find tokens like "5720-23 (major)" or "5714" or "5720 (major)"
    tokens = re.split(r',\s*', text.strip())
    for tok in tokens:
        tok = tok.strip()
        if not tok:
            continue
        is_major = bool(re.search(r'\(major\)', tok, re.IGNORECASE))
        clean = re.sub(r'\s*\(major\)', '', tok, flags=re.IGNORECASE).strip()
        if clean:
            try:
                price = _parse_tok(clean)
                out.append((price, is_major))
            except Exception:
                pass
    return out

def load_mancini_with_major():
    """Return dict: trading_date -> list of (price, is_major)."""
    conn = sqlite3.connect(ROOT / 'data' / 'levels.db')
    rows = conn.execute(
        "SELECT trading_date, supports, resistances FROM levels "
        "WHERE trading_date >= '2025-03-07' ORDER BY trading_date"
    ).fetchall()
    conn.close()

    result = {}
    for td, sup, res in rows:
        levels = _parse_man_with_major(sup) + _parse_man_with_major(res)
        if levels:
            result[td] = levels
    return result

# ── Relabel with 3 classes ─────────────────────────────────────────────────────

def relabel_3class(df, man_by_date):
    """
    For each Mancini level, assign the nearest candidate within MATCH_TOL:
      2 = Mancini major
      1 = Mancini minor
      0 = not matched (algo extra)
    """
    labels = np.zeros(len(df), dtype=np.int8)
    dates_arr  = df['trading_date'].values
    prices_arr = df['price_rounded'].values

    for td, man_levels in man_by_date.items():
        day_idx = np.where(dates_arr == td)[0]
        if len(day_idx) == 0:
            continue
        day_prices = prices_arr[day_idx]

        for price, is_major in man_levels:
            dists = np.abs(day_prices - price)
            best_i = dists.argmin()
            if dists[best_i] <= MATCH_TOL:
                labels[day_idx[best_i]] = 2 if is_major else 1

    df = df.copy()
    df['label3'] = labels
    return df

# ── Statistical comparison ─────────────────────────────────────────────────────

def compare_features(df, feat_cols):
    """
    Compare feature distributions across the 3 classes.
    For each feature: mean/median per class, Mann-Whitney p-value (major vs minor).
    """
    major = df[df.label3 == 2]
    minor = df[df.label3 == 1]
    extra = df[df.label3 == 0]

    rows = []
    for f in feat_cols:
        maj_vals = major[f].dropna()
        min_vals = minor[f].dropna()
        ext_vals = extra[f].dropna()

        if len(maj_vals) < 5 or len(min_vals) < 5:
            continue

        # Mann-Whitney U: major vs minor
        u_stat, p_mw = stats.mannwhitneyu(maj_vals, min_vals, alternative='two-sided')

        rows.append({
            'feature':        f,
            'major_mean':     round(maj_vals.mean(), 3),
            'major_median':   round(maj_vals.median(), 3),
            'minor_mean':     round(min_vals.mean(), 3),
            'minor_median':   round(min_vals.median(), 3),
            'extra_mean':     round(ext_vals.mean(), 3),
            'extra_median':   round(ext_vals.median(), 3),
            'p_major_vs_minor': round(p_mw, 4),
            'significant':    p_mw < 0.05,
        })

    result = pd.DataFrame(rows).sort_values('p_major_vs_minor')
    return result

# ── Proximity analysis ─────────────────────────────────────────────────────────

def proximity_analysis(df):
    """
    Check whether Mancini's major levels cluster near close4pm more than minor.
    Bins: 0-50, 50-100, 100-200, 200-325 pts from close4pm.
    """
    bins   = [0, 50, 100, 200, 325]
    labels = ['0-50', '50-100', '100-200', '200-325']
    df = df.copy()
    df['dist_bin'] = pd.cut(df['dist_from_4pm'], bins=bins, labels=labels, right=True)

    pivot = df[df.label3 >= 1].groupby(['dist_bin', 'label3']).size().unstack(fill_value=0)
    pivot.columns = ['minor' if c == 1 else 'major' for c in pivot.columns]
    pivot['total']     = pivot.sum(axis=1)
    pivot['pct_major'] = (pivot['major'] / pivot['total'] * 100).round(1)
    return pivot

# ── Simple decision tree for interpretability ──────────────────────────────────

def fit_decision_tree(df, feat_cols, max_depth=4):
    from sklearn.tree import DecisionTreeClassifier, export_text
    sub = df[df.label3 >= 1].copy()
    X = sub[feat_cols].fillna(0).values
    y = (sub['label3'] == 2).astype(int).values
    clf = DecisionTreeClassifier(max_depth=max_depth, min_samples_leaf=30, random_state=42)
    clf.fit(X, y)
    acc = (clf.predict(X) == y).mean()
    tree_text = export_text(clf, feature_names=feat_cols, max_depth=max_depth)
    importances = pd.Series(clf.feature_importances_, index=feat_cols).sort_values(ascending=False)
    return tree_text, importances, acc

# ── Main ───────────────────────────────────────────────────────────────────────

print("Loading feature matrix...")
df = pd.read_parquet(ROOT / 'data' / 'phase6e_features.parquet')
print(f"  {len(df):,} rows, {df['trading_date'].nunique()} dates "
      f"({df['trading_date'].min()} to {df['trading_date'].max()})")

print("Loading Mancini levels with major/minor tags...")
man_by_date = load_mancini_with_major()

# Count major vs minor across history
total_major = sum(sum(1 for _, is_m in v if is_m)     for v in man_by_date.values())
total_minor = sum(sum(1 for _, is_m in v if not is_m) for v in man_by_date.values())
print(f"  Mancini levels across {len(man_by_date)} dates: "
      f"{total_major} major, {total_minor} minor  "
      f"({total_major/(total_major+total_minor)*100:.1f}% major)")

print("Relabelling with 3 classes (0=extra, 1=minor, 2=major)...")
df = relabel_3class(df, man_by_date)

n0 = (df.label3 == 0).sum()
n1 = (df.label3 == 1).sum()
n2 = (df.label3 == 2).sum()
print(f"  0=extra: {n0:,}  1=minor: {n1:,}  2=major: {n2:,}")
print(f"  Of matched Mancini levels: {n2/(n1+n2)*100:.1f}% major")

# ── Feature comparison ─────────────────────────────────────────────────────────
feat_cols = [c for c in FEATURE_COLS if c in df.columns]

print("\n" + "="*70)
print("FEATURE COMPARISON: major vs minor (sorted by significance)")
print("="*70)
comp = compare_features(df, feat_cols)
print(comp.to_string(index=False))

# ── Proximity analysis ─────────────────────────────────────────────────────────
print("\n" + "="*70)
print("PROXIMITY TO CLOSE4PM: % of Mancini levels that are major, by distance band")
print("="*70)
prox = proximity_analysis(df)
print(prox.to_string())

# ── Decision tree ─────────────────────────────────────────────────────────────
print("\n" + "="*70)
print("DECISION TREE (major vs minor, depth=4, Mancini levels only)")
print("="*70)
try:
    tree_text, importances, acc = fit_decision_tree(df, feat_cols)
    print(f"Training accuracy: {acc*100:.1f}%")
    print("\nFeature importances:")
    for feat, imp in importances[importances > 0.01].items():
        print(f"  {feat:<30} {imp:.3f}")
    print("\nTree structure:")
    print(tree_text)
except ImportError:
    print("sklearn not available — skipping decision tree")

# ── Save to Excel ──────────────────────────────────────────────────────────────
OUT_PATH = ROOT / 'data' / 'major_minor_analysis.xlsx'
with pd.ExcelWriter(OUT_PATH, engine='openpyxl') as writer:
    comp.to_excel(writer, sheet_name='Feature Comparison', index=False)
    prox.to_excel(writer, sheet_name='Proximity Analysis')

    # Per-class summary stats
    summary_rows = []
    for label, name in [(0, 'extra'), (1, 'minor'), (2, 'major')]:
        sub = df[df.label3 == label]
        for f in feat_cols:
            vals = sub[f].dropna()
            summary_rows.append({
                'class': name, 'feature': f,
                'mean': round(vals.mean(), 3), 'median': round(vals.median(), 3),
                'std':  round(vals.std(),  3),
                'p10':  round(vals.quantile(0.1), 3),
                'p90':  round(vals.quantile(0.9), 3),
            })
    pd.DataFrame(summary_rows).to_excel(writer, sheet_name='Per-Class Stats', index=False)

print(f"\nSaved: {OUT_PATH}")
