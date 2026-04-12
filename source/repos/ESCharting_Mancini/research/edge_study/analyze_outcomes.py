"""
analyze_outcomes.py — Phase 2: Find the edge.

Loads the touch_events.parquet built by build_dataset.py and produces:
  1. Baseline stats (overall, long vs short, RTH vs ETH)
  2. Univariate analysis — win rate by each feature, binned
  3. Feature combination study — 2-way and 3-way combos
  4. XGBoost model on touch events — feature importance for win_30
  5. Checklist construction — scored conditions vs win rate

Primary outcome: win_30 (price hits +10pts before -5pts within 30 min)
Baseline context: 2:1 R:R. Breakeven = 33.3%. Target: find conditions ≥45%.

Usage:
    python analyze_outcomes.py
    python analyze_outcomes.py --window 60   # use win_60 instead
    python analyze_outcomes.py --out report.xlsx
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

OUT_DIR  = Path(__file__).parent / 'data'
REPO_ROOT = Path(__file__).parent.parent.parent

# ── parameters ────────────────────────────────────────────────────────────────
MIN_SAMPLE = 50      # minimum sample size to report a bin
WIN_COL    = 'win_30'
BREAKEVEN  = 1 / 3   # 33.3% for 2:1 R:R


# ── helpers ───────────────────────────────────────────────────────────────────

def winrate(series: pd.Series) -> tuple[float, int]:
    """Return (win_rate, n) for a series of 0/1/NaN values."""
    s = series.dropna()
    if len(s) < MIN_SAMPLE:
        return np.nan, len(s)
    return float(s.mean()), len(s)


def edge(wr: float) -> str:
    """Format win rate with edge marker."""
    if np.isnan(wr):
        return '  n/a  '
    pct = wr * 100
    if wr >= 0.55:
        marker = ' *** STRONG'
    elif wr >= 0.45:
        marker = ' **  GOOD'
    elif wr >= BREAKEVEN + 0.02:
        marker = ' *   edge'
    elif wr >= BREAKEVEN - 0.01:
        marker = '     ~break-even'
    else:
        marker = '     below BE'
    return f'{pct:5.1f}%{marker}'


def section(title: str):
    print(f'\n{"="*70}')
    print(f'  {title}')
    print('='*70)


def subsection(title: str):
    print(f'\n  -- {title} --')


def row_fmt(label: str, wr: float, n: int, base: float = None) -> str:
    diff = f'  ({wr - base:+.1%} vs base)' if base is not None and not np.isnan(wr) else ''
    return f'    {label:<35}  {edge(wr)}   n={n:,}{diff}'


# ── load data ─────────────────────────────────────────────────────────────────

def load(path: Path, win_col: str) -> pd.DataFrame:
    print(f'Loading {path.name}...', flush=True)
    df = pd.read_parquet(path)
    print(f'  {len(df):,} touch events', flush=True)

    # Work only with rows where outcome is defined
    df_w = df[df[win_col].notna()].copy()
    print(f'  {len(df_w):,} resolved within window  '
          f'({len(df_w)/len(df):.0%} resolution rate)', flush=True)
    print(f'  Baseline {win_col}: {df_w[win_col].mean():.1%}  '
          f'(breakeven = {BREAKEVEN:.1%})', flush=True)
    return df, df_w


# ── 1. Baseline stats ─────────────────────────────────────────────────────────

def baseline_stats(df: pd.DataFrame, df_w: pd.DataFrame, win_col: str):
    section('1. BASELINE STATS')

    base_wr, base_n = winrate(df_w[win_col])
    print(f'\n  Overall win rate: {edge(base_wr)}   n={base_n:,}')
    print(f'  Resolution rate: {df_w[win_col].notna().sum()/len(df):.1%} of all touches')

    subsection('By direction')
    for label, mask in [('Supports (long)', df_w.is_support == 1),
                        ('Resistances (short)', df_w.is_support == 0)]:
        wr, n = winrate(df_w.loc[mask, win_col])
        print(row_fmt(label, wr, n, base_wr))

    subsection('By session')
    for label, mask in [('RTH (09:30–16:00 ET)', df_w.is_rth == 1),
                        ('ETH (all other hours)', df_w.is_rth == 0)]:
        wr, n = winrate(df_w.loc[mask, win_col])
        print(row_fmt(label, wr, n, base_wr))

    subsection('Across all outcome windows')
    for col in ['win_10', 'win_30', 'win_60', 'win_120']:
        if col in df.columns:
            s = df[col].dropna()
            res_rate = len(s) / len(df)
            print(f'    {col:<10}  wr={s.mean():.1%}  n={len(s):,}  '
                  f'({res_rate:.0%} resolution)')

    return base_wr


# ── 2. Univariate analysis ────────────────────────────────────────────────────

def univariate(df_w: pd.DataFrame, win_col: str, base_wr: float):
    section('2. UNIVARIATE FEATURE ANALYSIS')
    print(f'  (baseline = {base_wr:.1%}, breakeven = {BREAKEVEN:.1%})')
    print(f'  Marked: *** ≥55%   ** ≥45%   * ≥35%   ~BE = ±2% of {BREAKEVEN:.0%}')

    # ── Binary / categorical features ────────────────────────────────────────
    subsection('Binary features (0 vs 1)')
    binary_feats = [
        ('is_rth',       'RTH session'),
        ('is_support',   'Support (long)'),
        ('sr_flip',      'S/R flip'),
        ('is_major',     'ML major (score≥0.5)'),
        ('is_mult5',     'Round number (mult of 5)'),
        ('vol_drying',   'Volume drying into level'),
        ('is_ath_cluster', 'ATH cluster level'),
    ]
    for feat, label in binary_feats:
        if feat not in df_w.columns:
            continue
        for val, vlabel in [(1, 'yes'), (0, 'no')]:
            wr, n = winrate(df_w.loc[df_w[feat] == val, win_col])
            print(row_fmt(f'{label} = {vlabel}', wr, n, base_wr))
        print()

    # ── Touch count ───────────────────────────────────────────────────────────
    subsection('Touch count today (how many prior touches of this level today)')
    for val in [0, 1, 2, 3]:
        mask = df_w.touch_n_today == val
        wr, n = winrate(df_w.loc[mask, win_col])
        label = f'touch_n_today = {val}' + (' (first touch)' if val == 0 else '')
        print(row_fmt(label, wr, n, base_wr))
    mask = df_w.touch_n_today >= 4
    wr, n = winrate(df_w.loc[mask, win_col])
    print(row_fmt('touch_n_today ≥ 4', wr, n, base_wr))

    # ── ML score ─────────────────────────────────────────────────────────────
    subsection('ML score bins (level quality from Phase 6e model)')
    bins = [0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.01]
    labels = ['0.0–0.2', '0.2–0.3', '0.3–0.4', '0.4–0.5',
              '0.5–0.6', '0.6–0.7', '0.7–0.8', '0.8–1.0']
    ml = df_w.ml_score.dropna()
    df_ml = df_w[df_w.ml_score.notna()].copy()
    df_ml['score_bin'] = pd.cut(df_ml.ml_score, bins=bins, labels=labels, right=False)
    for lbl in labels:
        mask = df_ml.score_bin == lbl
        wr, n = winrate(df_ml.loc[mask, win_col])
        print(row_fmt(f'ml_score {lbl}', wr, n, base_wr))

    # ── Approach velocity ─────────────────────────────────────────────────────
    subsection('Approach velocity (pts/bar over last 20 bars; neg = falling into support)')
    # For supports: negative approach = coming from above (good), positive = bouncing up already
    # For resistances: positive approach = coming from below (good), negative = already sold off
    # We use abs for "speed" and also directional for supports specifically
    df_sup = df_w[df_w.is_support == 1].copy()
    df_res = df_w[df_w.is_support == 0].copy()

    print('  Supports (long) — velocity toward level = negative:')
    vel_bins_s = [(-99, -0.5), (-0.5, -0.2), (-0.2, -0.05), (-0.05, 0.05),
                  (0.05, 0.2), (0.2, 99)]
    vel_labels_s = ['< -0.5 (running fast)', '-0.5 to -0.2 (fast)',
                    '-0.2 to -0.05 (slow)', '-0.05 to 0.05 (drifting)',
                    '0.05 to 0.2 (rising)', '> 0.2 (rising fast)']
    for (lo, hi), lbl in zip(vel_bins_s, vel_labels_s):
        mask = (df_sup.approach_vel >= lo) & (df_sup.approach_vel < hi)
        wr, n = winrate(df_sup.loc[mask, win_col])
        print(row_fmt(f'vel {lbl}', wr, n, base_wr))
    print()
    print('  Resistances (short) — velocity toward level = positive:')
    vel_bins_r = [(-99, -0.2), (-0.2, -0.05), (-0.05, 0.05),
                  (0.05, 0.2), (0.2, 0.5), (0.5, 99)]
    vel_labels_r = ['< -0.2 (falling)', '-0.2 to -0.05 (slow fall)',
                    '-0.05 to 0.05 (drifting)',
                    '0.05 to 0.2 (slow rise)', '0.2 to 0.5 (fast)',
                    '> 0.5 (running fast)']
    for (lo, hi), lbl in zip(vel_bins_r, vel_labels_r):
        mask = (df_res.approach_vel >= lo) & (df_res.approach_vel < hi)
        wr, n = winrate(df_res.loc[mask, win_col])
        print(row_fmt(f'vel {lbl}', wr, n, base_wr))

    # ── Time of day ───────────────────────────────────────────────────────────
    subsection('Time of day (ET)')
    tod_bins = [
        (0,    570,  'Overnight / pre-market  (00:00–09:30)'),
        (570,  660,  'Morning 1  (09:30–11:00)'),
        (660,  750,  'Morning 2  (11:00–12:30)'),
        (750,  870,  'Midday     (12:30–14:30)'),
        (870,  960,  'Afternoon  (14:30–16:00)'),
        (960,  1440, 'After-hours (16:00–24:00)'),
    ]
    for lo, hi, lbl in tod_bins:
        mask = (df_w.time_of_day_mins >= lo) & (df_w.time_of_day_mins < hi)
        wr, n = winrate(df_w.loc[mask, win_col])
        print(row_fmt(lbl, wr, n, base_wr))

    # ── Trend context ─────────────────────────────────────────────────────────
    subsection('Trend direction (60-min) — does trend align with the trade?')
    # Aligned = price trending INTO the level
    # For support (long): trend_dir_60 = -1 (downtrend INTO support) = aligned
    # For resistance (short): trend_dir_60 = +1 (uptrend INTO resistance) = aligned
    df_w = df_w.copy()
    df_w['trend_aligned_60'] = np.where(
        df_w.is_support == 1, (df_w.trend_dir_60 == -1).astype(int),
        (df_w.trend_dir_60 == 1).astype(int)
    )
    for val, lbl in [(1, 'Trend aligned (into level)'), (0, 'Trend counter (away from level)')]:
        mask = df_w.trend_aligned_60 == val
        wr, n = winrate(df_w.loc[mask, win_col])
        print(row_fmt(lbl, wr, n, base_wr))

    # 60-min trend strength
    print()
    subsection('Trend strength (60-min, pts) — how extended the move is into the level')
    for lo, hi, lbl in [(0, 5, '0–5 pts (barely moving)'),
                        (5, 15, '5–15 pts'), (15, 30, '15–30 pts'),
                        (30, 60, '30–60 pts'), (60, 9999, '60+ pts (extended)')]:
        mask = (df_w.trend_strength_60 >= lo) & (df_w.trend_strength_60 < hi)
        wr, n = winrate(df_w.loc[mask, win_col])
        print(row_fmt(f'{lbl}', wr, n, base_wr))

    # ── Volume at touch ───────────────────────────────────────────────────────
    subsection('Volume z-score at touch bar (vs 20-bar mean)')
    for lo, hi, lbl in [(-99, -0.5, 'Very low volume  (z < -0.5)'),
                        (-0.5, 0.5, 'Normal volume   (-0.5 to 0.5)'),
                        (0.5, 2.0,  'Elevated volume  (0.5 to 2.0)'),
                        (2.0, 99,   'Very high volume (z > 2.0)')]:
        mask = (df_w.vol_zscore_touch >= lo) & (df_w.vol_zscore_touch < hi)
        wr, n = winrate(df_w.loc[mask, win_col])
        print(row_fmt(lbl, wr, n, base_wr))

    # ── Distance from 4pm close ───────────────────────────────────────────────
    subsection('Distance from 4pm close (pts) — how far level is from anchor')
    for lo, hi, lbl in [(0, 25, '0–25 pts  (very close)'),
                        (25, 75, '25–75 pts'),
                        (75, 150, '75–150 pts'),
                        (150, 250, '150–250 pts'),
                        (250, 9999, '250+ pts  (far)')]:
        mask = (df_w.dist_from_4pm >= lo) & (df_w.dist_from_4pm < hi)
        wr, n = winrate(df_w.loc[mask, win_col])
        print(row_fmt(lbl, wr, n, base_wr))

    return df_w   # return with added columns


# ── 3. Feature combinations ───────────────────────────────────────────────────

def combinations(df_w: pd.DataFrame, win_col: str, base_wr: float):
    section('3. FEATURE COMBINATION STUDY')
    print(f'  Showing combinations with n≥{MIN_SAMPLE} and wr ≥ {BREAKEVEN+0.03:.0%}')
    print(f'  Sorted by win rate descending.\n')

    # Define candidate binary conditions
    conditions = {
        'RTH':          df_w.is_rth == 1,
        'ETH':          df_w.is_rth == 0,
        'Support':      df_w.is_support == 1,
        'Resistance':   df_w.is_support == 0,
        'First touch':  df_w.touch_n_today == 0,
        'SR flip':      df_w.sr_flip == 1,
        'Major':        df_w.is_major == 1,
        'Round #':      df_w.is_mult5 == 1,
        'Vol drying':   df_w.vol_drying == 1,
        'High score':   df_w.ml_score >= 0.6,
        'Very fast in': (df_w.is_support == 1) & (df_w.approach_vel < -0.3) |
                        (df_w.is_support == 0) & (df_w.approach_vel > 0.3),
        'Slow drift in': (df_w.is_support == 1) & (df_w.approach_vel.between(-0.15, 0)) |
                         (df_w.is_support == 0) & (df_w.approach_vel.between(0, 0.15)),
        'Trend aligned': df_w.get('trend_aligned_60', pd.Series(0, index=df_w.index)) == 1,
        'Morning':      (df_w.time_of_day_mins >= 570) & (df_w.time_of_day_mins < 720),
        'Afternoon':    (df_w.time_of_day_mins >= 840) & (df_w.time_of_day_mins < 960),
    }

    cond_keys = list(conditions.keys())
    results = []

    # 2-way combinations
    for i in range(len(cond_keys)):
        for j in range(i + 1, len(cond_keys)):
            k1, k2 = cond_keys[i], cond_keys[j]
            # Skip logically exclusive pairs
            if {k1, k2} in [{'Support', 'Resistance'}, {'RTH', 'ETH'}]:
                continue
            mask = conditions[k1] & conditions[k2]
            wr, n = winrate(df_w.loc[mask, win_col])
            if not np.isnan(wr) and wr >= BREAKEVEN + 0.03:
                results.append({'conditions': f'{k1} + {k2}', 'wr': wr, 'n': n, 'ndim': 2})

    # 3-way combinations (only from top 2-way pairs to keep it tractable)
    top2 = sorted(results, key=lambda r: r['wr'], reverse=True)[:20]
    for r in top2:
        parts = r['conditions'].split(' + ')
        k1, k2 = parts[0], parts[1]
        for k3 in cond_keys:
            if k3 in [k1, k2]:
                continue
            if {k1, k3} in [{'Support', 'Resistance'}, {'RTH', 'ETH'}]:
                continue
            if {k2, k3} in [{'Support', 'Resistance'}, {'RTH', 'ETH'}]:
                continue
            mask = conditions[k1] & conditions[k2] & conditions[k3]
            wr, n = winrate(df_w.loc[mask, win_col])
            if not np.isnan(wr) and wr >= BREAKEVEN + 0.05:
                results.append({'conditions': f'{k1} + {k2} + {k3}', 'wr': wr, 'n': n, 'ndim': 3})

    results.sort(key=lambda r: r['wr'], reverse=True)

    subsection('2-way combinations')
    for r in results:
        if r['ndim'] != 2:
            continue
        print(row_fmt(r['conditions'], r['wr'], r['n'], base_wr))

    subsection('3-way combinations')
    for r in results:
        if r['ndim'] != 3:
            continue
        print(row_fmt(r['conditions'], r['wr'], r['n'], base_wr))

    return results


# ── 4. XGBoost model on touch events ─────────────────────────────────────────

def xgboost_model(df_w: pd.DataFrame, win_col: str):
    section('4. XGBOOST ON TOUCH EVENTS — Feature Importance')

    try:
        import xgboost as xgb
        from sklearn.model_selection import cross_val_score
        from sklearn.metrics import roc_auc_score
    except ImportError:
        print('  xgboost or sklearn not available — skipping')
        return None

    feature_cols = [
        'is_support', 'is_rth', 'sr_flip', 'is_major', 'is_mult5', 'vol_drying',
        'ml_score', 'dist_from_4pm', 'historical_touches', 'days_since_pivot',
        'recency_rank', 'local_density', 'dist_round', 'historical_bounce',
        'price_crossings',
        'touch_n_today', 'approach_vel', 'approach_bars',
        'time_of_day_mins', 'trend_dir_60', 'trend_strength_60',
        'trend_dir_240', 'trend_strength_240',
        'vol_zscore_touch', 'vol_zscore_approach', 'atr_20',
        'dist_from_open', 'gap_pts',
    ]

    # Filter to available cols with no NaN
    avail = [c for c in feature_cols if c in df_w.columns]
    df_model = df_w[avail + [win_col]].dropna()
    if len(df_model) < 500:
        print('  Too few samples for modeling.')
        return None

    X = df_model[avail].values.astype(np.float32)
    y = df_model[win_col].values.astype(np.int32)

    print(f'  Training on {len(df_model):,} samples, {len(avail)} features', flush=True)

    model = xgb.XGBClassifier(
        n_estimators=300, max_depth=4, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8,
        eval_metric='logloss', random_state=42,
        early_stopping_rounds=20,
    )

    # Simple train/test split (last 20% as test to respect time ordering)
    split = int(len(df_model) * 0.8)
    X_tr, X_te = X[:split], X[split:]
    y_tr, y_te = y[:split], y[split:]

    model.fit(X_tr, y_tr, eval_set=[(X_te, y_te)], verbose=False)
    y_prob = model.predict_proba(X_te)[:, 1]
    auc = roc_auc_score(y_te, y_prob)
    wr_pred_high = float(pd.Series(y_te)[y_prob >= 0.5].mean()) if (y_prob >= 0.5).any() else np.nan

    print(f'  Test AUC: {auc:.3f}  (0.5 = random, 1.0 = perfect)')
    if not np.isnan(wr_pred_high):
        n_high = int((y_prob >= 0.5).sum())
        print(f'  Win rate when model score ≥ 0.5: {wr_pred_high:.1%}  (n={n_high:,})')

    # Feature importance
    imp = pd.Series(model.feature_importances_, index=avail).sort_values(ascending=False)
    print(f'\n  Feature importance (top 20):')
    for feat, val in imp.head(20).items():
        bar = '█' * int(val * 200)
        print(f'    {feat:<30}  {val:.4f}  {bar}')

    return model, imp


# ── 5. Checklist construction ─────────────────────────────────────────────────

def build_checklist(df_w: pd.DataFrame, win_col: str, base_wr: float, combo_results: list):
    section('5. CHECKLIST — Scored Setup Quality')
    print(f'  Each condition = 1 point. Win rate vs total score.\n')
    print(f'  Base rate: {base_wr:.1%}. Breakeven: {BREAKEVEN:.1%}.\n')

    # Define checklist items based on univariate findings
    checklist = {
        'RTH session':           df_w.is_rth == 1,
        'First touch today':     df_w.touch_n_today == 0,
        'SR flip':               df_w.sr_flip == 1,
        'ML major (score≥0.5)':  df_w.is_major == 1,
        'High ML score (≥0.6)':  df_w.ml_score >= 0.6,
        'Round number (×5)':     df_w.is_mult5 == 1,
        'Vol drying':            df_w.vol_drying == 1,
        'Trend aligned (60m)':   df_w.get('trend_aligned_60', pd.Series(0, index=df_w.index)) == 1,
        'Slow approach':         (df_w.is_support == 1) & df_w.approach_vel.between(-0.2, 0) |
                                 (df_w.is_support == 0) & df_w.approach_vel.between(0, 0.2),
    }

    df_check = df_w.copy()
    df_check['score'] = sum(cond.astype(int) for cond in checklist.values())

    print(f'  {"Score":<8}  {"Win rate":>10}  {"n":>8}  {"Edge"}')
    print(f'  {"─"*55}')
    all_scores = sorted(df_check['score'].unique())
    for s in all_scores:
        mask = df_check['score'] == s
        wr, n = winrate(df_check.loc[mask, win_col])
        bar = '' if np.isnan(wr) else '▓' * max(0, int((wr - base_wr) * 100))
        diff = f'{wr - base_wr:+.1%}' if not np.isnan(wr) else '   n/a'
        print(f'  {s:<8}  {wr*100:>9.1f}%  {n:>8,}  {diff}  {bar}')

    print(f'\n  Recommendation:')
    # Find minimum score that gives ≥45% win rate
    threshold_found = False
    for s in sorted(all_scores, reverse=True):
        mask = df_check['score'] >= s
        wr, n = winrate(df_check.loc[mask, win_col])
        if not np.isnan(wr) and wr >= 0.45 and n >= MIN_SAMPLE:
            print(f'    Score ≥ {s}: win rate = {wr:.1%} (n={n:,}) — recommended minimum')
            threshold_found = True
            break
    if not threshold_found:
        print('    No threshold reaches 45% with current data — see combination study above.')

    return df_check


# ── 6. Failed breakdown deep-dive ─────────────────────────────────────────────

def failed_breakdown_study(df_w_all: pd.DataFrame):
    section('6. FAILED BREAKDOWN STUDY (supports only)')

    df_sup = df_w_all[df_w_all.is_support == 1].copy()
    total = len(df_sup)
    if 'broke_below' not in df_sup.columns:
        print('  broke_below column missing — skipping')
        return

    broke = df_sup.broke_below.dropna()
    n_broke = int(broke.sum())
    print(f'\n  Support touches: {total:,}')
    print(f'  Broke below level: {n_broke:,} ({n_broke/len(broke):.1%})')

    reclaimed = df_sup[df_sup.broke_below == 1]['reclaimed_after_break'].dropna()
    n_reclaimed = int(reclaimed.sum())
    print(f'  Of those, reclaimed: {n_reclaimed:,} ({n_reclaimed/max(len(reclaimed),1):.1%})')
    print(f'  → Failed breakdown rate: {n_reclaimed/max(total,1):.1%} of all support touches')

    if n_reclaimed < MIN_SAMPLE:
        print('  Too few reclaim events for feature analysis.')
        return

    # What characterizes a reclaim vs a continued breakdown?
    df_broke = df_sup[df_sup.broke_below == 1].copy()
    subsection('Features: reclaimed (FB trade) vs stayed broken')
    feat_compare = ['ml_score', 'is_rth', 'sr_flip', 'touch_n_today',
                    'approach_vel', 'vol_drying', 'is_major', 'trend_strength_60']
    for feat in feat_compare:
        if feat not in df_broke.columns:
            continue
        rec_vals   = df_broke.loc[df_broke.reclaimed_after_break == 1, feat].dropna()
        broke_vals = df_broke.loc[df_broke.reclaimed_after_break == 0, feat].dropna()
        if len(rec_vals) < 10 or len(broke_vals) < 10:
            continue
        print(f'    {feat:<30}  reclaimed={rec_vals.mean():.3f}  '
              f'stayed_broken={broke_vals.mean():.3f}  '
              f'diff={rec_vals.mean()-broke_vals.mean():+.3f}')


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--parquet', default=str(OUT_DIR / 'touch_events.parquet'))
    parser.add_argument('--window', type=int, default=30,
                        help='Outcome window in minutes (10/30/60/120)')
    parser.add_argument('--out', default=None,
                        help='Optional Excel output path')
    args = parser.parse_args()

    global WIN_COL
    WIN_COL = f'win_{args.window}'

    path = Path(args.parquet)
    if not path.exists():
        print(f'ERROR: {path} not found. Run build_dataset.py first.')
        sys.exit(1)

    df_all, df_w = load(path, WIN_COL)

    base_wr = baseline_stats(df_all, df_w, WIN_COL)
    df_w    = univariate(df_w, WIN_COL, base_wr)
    combos  = combinations(df_w, WIN_COL, base_wr)
    xgb_res = xgboost_model(df_w, WIN_COL)
    df_check = build_checklist(df_w, WIN_COL, base_wr, combos)
    failed_breakdown_study(df_all)

    section('DONE')
    print(f'\n  Dataset: {len(df_all):,} touch events')
    print(f'  Primary outcome: {WIN_COL} (2:1 R:R: +10pts target / -5pts stop)')
    print(f'  Baseline win rate: {base_wr:.1%}  (breakeven {BREAKEVEN:.1%})')
    print(f'\n  Next steps:')
    print('  → analyze_combinations.py  (deeper 3-4 way combo study)')
    print('  → analyze_failed_breakdowns.py  (FB trade deep dive)')

    # Optional Excel export
    if args.out:
        out_path = Path(args.out)
        combo_df = pd.DataFrame(combos).sort_values('wr', ascending=False)
        with pd.ExcelWriter(out_path, engine='openpyxl') as xw:
            df_all.head(500).to_excel(xw, sheet_name='Sample', index=False)
            combo_df.to_excel(xw, sheet_name='Combinations', index=False)
            df_check.groupby('score')[WIN_COL].agg(['mean', 'count']).to_excel(
                xw, sheet_name='Checklist')
        print(f'\n  Excel saved: {out_path}')


if __name__ == '__main__':
    main()
