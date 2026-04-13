"""
analyze_failed_breakdowns.py — Deep dive on two setups:

A. Failed Breakdown (FB): Support breaks below, then reclaims within 30 bars.
   Entry logic: enter LONG on the first bar that closes back above the level.
   Question: what predicts whether a break will reclaim?

B. Afternoon session deep dive:
   Is the afternoon edge consistent? Which level types? Year by year? Long vs short?

Usage:
    python analyze_failed_breakdowns.py
    python analyze_failed_breakdowns.py --out data/fb_results.xlsx
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

OUT_DIR   = Path(__file__).parent / 'data'
BREAKEVEN = 1 / 3
MIN_SAMPLE = 30

# ── helpers ───────────────────────────────────────────────────────────────────

def winrate(series):
    s = series.dropna()
    if len(s) < MIN_SAMPLE:
        return np.nan, len(s)
    return float(s.mean()), len(s)


def section(title):
    print(f'\n{"="*70}')
    print(f'  {title}')
    print('='*70)


def subsection(title):
    print(f'\n  -- {title} --')


def row_fmt(label, wr, n, base=None):
    if np.isnan(wr):
        return f'    {label:<40}   n/a    n={n:,}'
    pct = wr * 100
    if wr >= 0.55:   marker = '*** STRONG'
    elif wr >= 0.45: marker = '**  GOOD'
    elif wr >= BREAKEVEN + 0.02: marker = '*   edge'
    elif wr >= BREAKEVEN - 0.01: marker = '    ~BE'
    else:            marker = '    below BE'
    diff = f'  ({wr - base:+.1%} vs base)' if base is not None else ''
    return f'    {label:<40}  {pct:5.1f}%  {marker}   n={n:,}{diff}'


def pct_of(n, total):
    return f'{n:,} ({n/max(total,1):.1%})'


# ── A. FAILED BREAKDOWN ANALYSIS ─────────────────────────────────────────────

def failed_breakdown_deep_dive(df):
    section('A. FAILED BREAKDOWN DEEP DIVE')

    df_sup = df[df.is_support == 1].copy()
    total  = len(df_sup)

    if 'broke_below' not in df_sup.columns:
        print('  broke_below column not found. Rebuild dataset.')
        return

    broke     = df_sup[df_sup.broke_below.notna()]
    n_broke   = int(broke.broke_below.sum())
    n_held    = len(broke) - n_broke
    reclaimed = df_sup[(df_sup.broke_below == 1) & df_sup.reclaimed_after_break.notna()]
    n_reclaim = int(reclaimed.reclaimed_after_break.sum())
    n_stayed  = len(reclaimed) - n_reclaim

    print(f'\n  Support touches (all):          {total:,}')
    print(f'  Level held (no break):          {pct_of(n_held, len(broke))}')
    print(f'  Level broke below:              {pct_of(n_broke, len(broke))}')
    print(f'  Of breaks: reclaimed (FB trade): {pct_of(n_reclaim, len(reclaimed))}')
    print(f'  Of breaks: stayed broken:        {pct_of(n_stayed, len(reclaimed))}')
    print(f'\n  FB rate vs all support touches:  {n_reclaim/total:.1%}')

    # ── Time of day: when do FBs occur? ──────────────────────────────────────
    subsection('Time of day — FB rate by session')
    tod_bins = [
        (0,    570,  'Pre-market   (00:00-09:30)'),
        (570,  660,  'Morning 1    (09:30-11:00)'),
        (660,  750,  'Morning 2    (11:00-12:30)'),
        (750,  870,  'Midday       (12:30-14:30)'),
        (870,  960,  'Afternoon    (14:30-16:00)'),
        (960,  1440, 'After-hours  (16:00-24:00)'),
    ]
    print(f'  {"Session":<35}  {"Broke%":>8}  {"Reclaim%":>10}  {"FB rate":>8}  n_touches')
    for lo, hi, lbl in tod_bins:
        mask = (df_sup.time_of_day_mins >= lo) & (df_sup.time_of_day_mins < hi)
        sub  = df_sup[mask]
        if len(sub) < MIN_SAMPLE:
            continue
        sub_broke    = sub[sub.broke_below.notna()]
        b_rate       = sub_broke.broke_below.mean() if len(sub_broke) > 0 else np.nan
        sub_rec      = sub[(sub.broke_below == 1) & sub.reclaimed_after_break.notna()]
        r_rate       = sub_rec.reclaimed_after_break.mean() if len(sub_rec) >= MIN_SAMPLE else np.nan
        fb_rate      = b_rate * r_rate if not (np.isnan(b_rate) or np.isnan(r_rate)) else np.nan
        r_str  = f'{r_rate:.1%}' if not np.isnan(r_rate) else '  n/a '
        fb_str = f'{fb_rate:.1%}' if not np.isnan(fb_rate) else '  n/a '
        print(f'  {lbl:<35}  {b_rate:>7.1%}  {r_str:>10}  {fb_str:>8}  {len(sub):,}')

    # ── What predicts reclaim vs stayed broken? ────────────────────────────────
    subsection('Feature comparison: reclaimed vs stayed broken')
    df_broke = df_sup[(df_sup.broke_below == 1) & df_sup.reclaimed_after_break.notna()].copy()
    rec_mask  = df_broke.reclaimed_after_break == 1
    brk_mask  = df_broke.reclaimed_after_break == 0
    rec_sub   = df_broke[rec_mask]
    brk_sub   = df_broke[brk_mask]
    print(f'\n  n(reclaimed)={len(rec_sub):,}   n(stayed broken)={len(brk_sub):,}')

    continuous = ['ml_score', 'approach_vel', 'trend_strength_60', 'trend_strength_240',
                  'vol_zscore_touch', 'vol_zscore_approach', 'atr_20',
                  'dist_from_4pm', 'dist_from_open', 'touch_n_today',
                  'days_since_pivot', 'historical_touches', 'local_density']
    print(f'\n  {"Feature":<30}  {"Reclaimed":>12}  {"Stayed broken":>14}  {"Diff":>8}')
    print(f'  {"-"*70}')
    diffs = []
    for feat in continuous:
        if feat not in df_broke.columns:
            continue
        r_mean = rec_sub[feat].dropna().mean()
        b_mean = brk_sub[feat].dropna().mean()
        diff   = r_mean - b_mean
        diffs.append((abs(diff) / (abs(r_mean) + 1e-6), feat, r_mean, b_mean, diff))
    diffs.sort(reverse=True)
    for _, feat, r_mean, b_mean, diff in diffs:
        arrow = '^' if diff > 0 else 'v'
        print(f'  {feat:<30}  {r_mean:>12.3f}  {b_mean:>14.3f}  {diff:>+7.3f} {arrow}')

    binary = ['is_rth', 'sr_flip', 'is_major', 'is_mult5', 'vol_drying']
    print(f'\n  {"Binary feature":<30}  {"Reclaimed %":>12}  {"Stayed broken %":>16}  {"Diff":>8}')
    print(f'  {"-"*72}')
    for feat in binary:
        if feat not in df_broke.columns:
            continue
        r_rate = rec_sub[feat].mean()
        b_rate = brk_sub[feat].mean()
        diff   = r_rate - b_rate
        arrow  = '^' if diff > 0 else 'v'
        print(f'  {feat:<30}  {r_rate:>11.1%}  {b_rate:>15.1%}  {diff:>+7.1%} {arrow}')

    # ── XGBoost: predict reclaim ───────────────────────────────────────────────
    subsection('XGBoost: predict whether a break will reclaim')
    _fb_model(df_broke)

    # ── Year-by-year FB stats ──────────────────────────────────────────────────
    subsection('Year-by-year failed breakdown rates')
    if 'anchor_date' in df_sup.columns:
        df_sup_c = df_sup.copy()
        df_sup_c['year'] = pd.to_datetime(df_sup_c.anchor_date).dt.year
    elif 'touch_time' in df_sup.columns:
        df_sup_c = df_sup.copy()
        df_sup_c['year'] = pd.to_datetime(df_sup_c.touch_time).dt.year
    else:
        print('  No date column found for year breakdown.')
        df_sup_c = None

    if df_sup_c is not None:
        print(f'\n  {"Year":<6}  {"Broke%":>8}  {"Reclaim%":>10}  {"FB rate":>8}  n')
        for yr in sorted(df_sup_c.year.dropna().unique()):
            sub = df_sup_c[df_sup_c.year == yr]
            sub_broke = sub[sub.broke_below.notna()]
            b_rate = sub_broke.broke_below.mean() if len(sub_broke) > 0 else np.nan
            sub_rec = sub[(sub.broke_below == 1) & sub.reclaimed_after_break.notna()]
            r_rate = sub_rec.reclaimed_after_break.mean() if len(sub_rec) >= 10 else np.nan
            fb_rate = b_rate * r_rate if not (np.isnan(b_rate) or np.isnan(r_rate)) else np.nan
            r_str  = f'{r_rate:.1%}' if not np.isnan(r_rate) else '  n/a '
            fb_str = f'{fb_rate:.1%}' if not np.isnan(fb_rate) else '  n/a '
            print(f'  {int(yr):<6}  {b_rate:>7.1%}  {r_str:>10}  {fb_str:>8}  {len(sub):,}')

    # ── Best conditions for FB trade ───────────────────────────────────────────
    subsection('What conditions best predict a reclaim?')
    print(f'  (base reclaim rate when broke = {n_reclaim/max(len(reclaimed),1):.1%})')
    base_rec = n_reclaim / max(len(reclaimed), 1)

    conditions = {
        'RTH':              df_broke.is_rth == 1,
        'ETH':              df_broke.is_rth == 0,
        'First touch':      df_broke.touch_n_today == 0,
        'SR flip':          df_broke.sr_flip == 1,
        'Major':            df_broke.is_major == 1,
        'Round #':          df_broke.is_mult5 == 1,
        'Vol drying':       df_broke.vol_drying == 1,
        'Fast approach':    df_broke.approach_vel < -0.3,
        'Slow approach':    df_broke.approach_vel.between(-0.2, 0),
        'Afternoon':        (df_broke.time_of_day_mins >= 870) & (df_broke.time_of_day_mins < 960),
        'Morning':          (df_broke.time_of_day_mins >= 570) & (df_broke.time_of_day_mins < 720),
        'High score':       df_broke.ml_score >= 0.6,
        'Low score':        df_broke.ml_score < 0.3,
    }

    results = []
    for name, mask in conditions.items():
        sub = df_broke[mask]
        if len(sub) < MIN_SAMPLE:
            continue
        r = sub.reclaimed_after_break.dropna()
        if len(r) < MIN_SAMPLE:
            continue
        wr = float(r.mean())
        results.append((wr, name, len(r)))
    results.sort(reverse=True)
    for wr, name, n in results:
        diff = wr - base_rec
        arrow = '^' if diff > 0 else 'v'
        print(f'    {name:<25}  {wr:.1%}  ({diff:+.1%} vs base) {arrow}   n={n:,}')


def _fb_model(df_broke):
    try:
        import xgboost as xgb
        from sklearn.metrics import roc_auc_score
    except ImportError:
        print('  xgboost not available')
        return

    feature_cols = [
        'is_rth', 'sr_flip', 'is_major', 'is_mult5', 'vol_drying',
        'ml_score', 'dist_from_4pm', 'approach_vel', 'touch_n_today',
        'time_of_day_mins', 'trend_dir_60', 'trend_strength_60',
        'vol_zscore_touch', 'atr_20', 'dist_from_open',
    ]
    avail = [c for c in feature_cols if c in df_broke.columns]
    df_m  = df_broke[avail + ['reclaimed_after_break']].dropna()
    if len(df_m) < 200:
        print('  Too few samples.')
        return

    X = df_m[avail].values.astype(np.float32)
    y = df_m['reclaimed_after_break'].values.astype(np.int32)

    split = int(len(df_m) * 0.8)
    model = xgb.XGBClassifier(n_estimators=200, max_depth=4, learning_rate=0.05,
                               subsample=0.8, colsample_bytree=0.8,
                               eval_metric='logloss', random_state=42,
                               early_stopping_rounds=20)
    model.fit(X[:split], y[:split], eval_set=[(X[split:], y[split:])], verbose=False)
    y_prob = model.predict_proba(X[split:])[:, 1]
    auc    = roc_auc_score(y[split:], y_prob)
    print(f'\n  AUC for predicting reclaim: {auc:.3f}')

    imp = pd.Series(model.feature_importances_, index=avail).sort_values(ascending=False)
    print('  Feature importance:')
    for feat, val in imp.head(10).items():
        bar = '|' * int(val * 150)
        print(f'    {feat:<30}  {val:.4f}  {bar}')


# ── B. AFTERNOON SESSION DEEP DIVE ────────────────────────────────────────────

def afternoon_deep_dive(df):
    section('B. AFTERNOON SESSION DEEP DIVE (14:30-16:00 ET)')

    WIN_COL = 'win_30'
    base_wr = df[WIN_COL].dropna().mean()
    print(f'\n  Overall baseline: {base_wr:.1%}  (breakeven {BREAKEVEN:.1%})')

    is_afternoon = (df.time_of_day_mins >= 870) & (df.time_of_day_mins < 960)
    df_aft = df[is_afternoon & df[WIN_COL].notna()].copy()
    wr_aft, n_aft = winrate(df_aft[WIN_COL])
    print(f'  Afternoon all touches: {wr_aft:.1%}  n={n_aft:,}')

    # ── Year by year consistency ───────────────────────────────────────────────
    subsection('Year-by-year win rate (afternoon only, win_30)')
    if 'anchor_date' in df_aft.columns:
        df_aft['year'] = pd.to_datetime(df_aft.anchor_date).dt.year
    elif 'touch_time' in df_aft.columns:
        df_aft['year'] = pd.to_datetime(df_aft.touch_time).dt.year
    else:
        df_aft['year'] = None

    if df_aft['year'].notna().any():
        print(f'\n  {"Year":<6}  {"Win rate":>10}  {"n":>7}  {"vs base":>8}')
        for yr in sorted(df_aft.year.dropna().unique()):
            sub = df_aft[df_aft.year == yr]
            wr, n = winrate(sub[WIN_COL])
            diff  = f'{wr - base_wr:+.1%}' if not np.isnan(wr) else '  n/a'
            print(f'  {int(yr):<6}  {wr*100:>9.1f}%  {n:>7,}  {diff:>8}')

    # ── Long vs short in afternoon ─────────────────────────────────────────────
    subsection('Supports vs resistances in afternoon')
    for label, mask in [('Supports  (long)', df_aft.is_support == 1),
                        ('Resistances (short)', df_aft.is_support == 0)]:
        wr, n = winrate(df_aft.loc[mask, WIN_COL])
        print(row_fmt(label, wr, n, wr_aft))

    # ── Afternoon win rate by level type ──────────────────────────────────────
    subsection('Level type in afternoon')
    conditions = {
        'First touch today':       df_aft.touch_n_today == 0,
        'Repeat touch (2nd+)':     df_aft.touch_n_today >= 1,
        'SR flip':                 df_aft.sr_flip == 1,
        'Not SR flip':             df_aft.sr_flip == 0,
        'ML major (score>=0.5)':   df_aft.is_major == 1,
        'ML minor (score<0.5)':    df_aft.is_major == 0,
        'High score (>=0.6)':      df_aft.ml_score >= 0.6,
        'Low score (<0.3)':        df_aft.ml_score < 0.3,
        'Round # (mult 5)':        df_aft.is_mult5 == 1,
        'Far from anchor (>75pt)': df_aft.dist_from_4pm > 75,
        'Close to anchor (<25pt)': df_aft.dist_from_4pm < 25,
    }
    for name, mask in conditions.items():
        wr, n = winrate(df_aft.loc[mask, WIN_COL])
        print(row_fmt(name, wr, n, wr_aft))

    # ── Approach velocity in afternoon ────────────────────────────────────────
    subsection('Approach velocity in afternoon')
    df_sup_aft = df_aft[df_aft.is_support == 1]
    df_res_aft = df_aft[df_aft.is_support == 0]
    print('  Supports:')
    for (lo, hi), lbl in [
        ((-99, -0.5), 'Running fast into support (vel < -0.5)'),
        ((-0.5, -0.2), 'Fast (-0.5 to -0.2)'),
        ((-0.2, -0.05), 'Slow (-0.2 to -0.05)'),
        ((-0.05, 0.05), 'Drifting'),
        ((0.05, 99), 'Rising (counter-trend retest)'),
    ]:
        mask = (df_sup_aft.approach_vel >= lo) & (df_sup_aft.approach_vel < hi)
        wr, n = winrate(df_sup_aft.loc[mask, WIN_COL])
        print(row_fmt(f'  {lbl}', wr, n, wr_aft))
    print('  Resistances:')
    for (lo, hi), lbl in [
        ((-99, -0.2), 'Falling (counter-trend retest)'),
        ((-0.2, 0.05), 'Slow / drifting'),
        ((0.05, 0.5), 'Rising fast into resistance'),
        ((0.5, 99), 'Running fast (vel > 0.5)'),
    ]:
        mask = (df_res_aft.approach_vel >= lo) & (df_res_aft.approach_vel < hi)
        wr, n = winrate(df_res_aft.loc[mask, WIN_COL])
        print(row_fmt(f'  {lbl}', wr, n, wr_aft))

    # ── Fine time slicing within afternoon ────────────────────────────────────
    subsection('Fine time splits within afternoon')
    fine_bins = [
        (870, 900, '14:30-15:00 (first 30 min)'),
        (900, 930, '15:00-15:30'),
        (930, 960, '15:30-16:00 (last 30 min, MOC flow)'),
    ]
    for lo, hi, lbl in fine_bins:
        mask = (df.time_of_day_mins >= lo) & (df.time_of_day_mins < hi) & df[WIN_COL].notna()
        wr, n = winrate(df.loc[mask, WIN_COL])
        print(row_fmt(lbl, wr, n, base_wr))

    # ── Best afternoon combos ─────────────────────────────────────────────────
    subsection('Best afternoon combos')
    combos = {
        'First touch':                          df_aft.touch_n_today == 0,
        'First touch + SR flip':                (df_aft.touch_n_today == 0) & (df_aft.sr_flip == 1),
        'First touch + Major':                  (df_aft.touch_n_today == 0) & (df_aft.is_major == 1),
        'First touch + Round #':                (df_aft.touch_n_today == 0) & (df_aft.is_mult5 == 1),
        'First touch + Slow approach (sup)':    (df_aft.touch_n_today == 0) & (df_aft.is_support == 1) &
                                                df_aft.approach_vel.between(-0.2, 0),
        'First touch + Slow approach (res)':    (df_aft.touch_n_today == 0) & (df_aft.is_support == 0) &
                                                df_aft.approach_vel.between(0, 0.2),
        'First touch + SR flip + Round #':      (df_aft.touch_n_today == 0) & (df_aft.sr_flip == 1) &
                                                (df_aft.is_mult5 == 1),
        'First touch + SR flip + Major':        (df_aft.touch_n_today == 0) & (df_aft.sr_flip == 1) &
                                                (df_aft.is_major == 1),
        'First touch + 15:30-16:00':            (df_aft.touch_n_today == 0) &
                                                (df_aft.time_of_day_mins >= 930),
        'First touch + slow + SR flip':         (df_aft.touch_n_today == 0) & (df_aft.sr_flip == 1) &
                                                (df_aft.approach_vel.abs() < 0.2),
    }
    results = []
    for name, mask in combos.items():
        wr, n = winrate(df_aft.loc[mask, WIN_COL])
        if not np.isnan(wr):
            results.append((wr, name, n))
    results.sort(reverse=True)
    for wr, name, n in results:
        print(row_fmt(name, wr, n, wr_aft))

    # ── Outcome window comparison ──────────────────────────────────────────────
    subsection('Outcome windows — afternoon first touch')
    mask_ft = (is_afternoon & (df.touch_n_today == 0))
    for col in ['win_10', 'win_30', 'win_60', 'win_120']:
        if col in df.columns:
            wr, n = winrate(df.loc[mask_ft, col])
            print(row_fmt(f'{col} (first touch)', wr, n, df[col].dropna().mean()))

    return df_aft


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--parquet', default=str(OUT_DIR / 'touch_events.parquet'))
    parser.add_argument('--out', default=None)
    args = parser.parse_args()

    path = Path(args.parquet)
    if not path.exists():
        print(f'ERROR: {path} not found. Run build_dataset.py first.')
        sys.exit(1)

    print(f'Loading {path.name}...', flush=True)
    df = pd.read_parquet(path)
    print(f'  {len(df):,} touch events', flush=True)

    failed_breakdown_deep_dive(df)
    df_aft = afternoon_deep_dive(df)

    section('SUMMARY')
    print("""
  Two primary setups to evaluate:

  SETUP A — Failed Breakdown (FB):
    Trigger:  Support level breaks (closes below) during RTH
    Entry:    First bar that closes back ABOVE the level
    Stop:     Below the breakdown candle low (~5pts)
    Target:   +10pts from entry
    Edge:     RTH breaks reclaim 70%+; see feature table above for best conditions

  SETUP B — Afternoon First Touch:
    Trigger:  Level untouched all day; price first reaches it 14:30-16:00 ET
    Entry:    At the touch of the level
    Stop:     5pts against
    Target:   10pts favorable
    Edge:     51%+ on first touch; 62%+ with slow approach; see fine combos above
    Note:     15:30-16:00 (last 30 min) may be strongest subslot — see fine splits
""")

    if args.out:
        out_path = Path(args.out)
        with pd.ExcelWriter(out_path, engine='openpyxl') as xw:
            df.head(500).to_excel(xw, sheet_name='Sample', index=False)
            aft_summary = (
                df[(df.time_of_day_mins >= 870) & (df.time_of_day_mins < 960) &
                   df.win_30.notna()]
                .groupby('touch_n_today')['win_30']
                .agg(['mean', 'count'])
                .rename(columns={'mean': 'win_rate', 'count': 'n'})
            )
            aft_summary.to_excel(xw, sheet_name='Afternoon_by_touch_n')
        print(f'\n  Excel saved: {out_path}')


if __name__ == '__main__':
    main()
