"""
Phase 6 Round 3: Candidate pool reduction strategies.

Baseline (6b): ~1000 candidates/day, 5.5% base rate => precision ceiling ~18%.
Goal: shrink pool to ~100-200 candidates/day => higher base rate => break ceiling.

Two strategies tested (separately and combined):
  A. Recency filter:     only consider pivots from the last N calendar days
  B. Significance filter: only top N pivots by swing quality (prominence * bounce)
  + Improved sr_flip: uses confirmed pivot arrays instead of raw bar h/l

Configurations run:
  1. Baseline (no filter)        -- for direct comparison
  2. Recency 365d                -- last 1yr
  3. Recency 180d                -- last 6mo
  4. Sig top-50/side             -- top 50 highs + 50 lows
  5. Sig top-30/side             -- top 30 highs + 30 lows
  6. Recency 365d + Sig top-50   -- combined
  7. Recency 180d + Sig top-30   -- combined (most aggressive)
"""

import numpy as np
import pandas as pd
import sqlite3, re as _re
from pathlib import Path

ROOT = Path(__file__).parent.parent

MATCH_TOL = 2.0

# ── Mancini label helpers ──────────────────────────────────────────────────────

def _parse_tok(tok):
    tok = tok.strip().strip(',')
    m = _re.match(r'^(\d+)-(\d+)$', tok)
    if m:
        a, b = m.group(1), m.group(2)
        b = (a[:len(a)-len(b)] + b) if len(b) < len(a) else b
        return (float(a) + float(b)) / 2
    return float(tok)

def _parse_man(text):
    if not text: return []
    clean = _re.sub(r'\s*\(major\)', '', text)
    out = []
    for p in clean.split(','):
        p = p.strip()
        if p:
            try: out.append(_parse_tok(p))
            except: pass
    return out

def _nn_relabel(df):
    """Nearest-neighbour relabelling: for each Mancini level, only the
    single closest candidate within MATCH_TOL gets label=1."""
    conn = sqlite3.connect(ROOT / 'data' / 'levels.db')
    man_rows = conn.execute(
        "SELECT trading_date, supports, resistances FROM levels "
        "WHERE trading_date >= '2025-03-07' ORDER BY trading_date"
    ).fetchall()
    conn.close()
    man_by_date = {td: _parse_man(ms) + _parse_man(mr) for td, ms, mr in man_rows}

    nn_labels  = np.zeros(len(df), dtype=np.int8)
    dates_arr  = df['trading_date'].values
    prices_arr = df['price'].values

    for td, man_levels in man_by_date.items():
        if not man_levels: continue
        day_idx = np.where(dates_arr == td)[0]
        if len(day_idx) == 0: continue
        day_prices = prices_arr[day_idx]
        for ml in man_levels:
            dists = np.abs(day_prices - ml)
            best_i = dists.argmin()
            if dists[best_i] <= MATCH_TOL:
                nn_labels[day_idx[best_i]] = 1

    df = df.copy()
    df['label'] = nn_labels
    return df

# ── Feature columns ────────────────────────────────────────────────────────────

FEATURE_COLS = [
    'pivot_type', 'is_support',
    'bounce', 'touches', 'local_density', 'prominence',
    'vol_zscore', 'consolidation', 'clean_departure',
    'sr_flip', 'price_crossings',
    'dist_from_4pm', 'dist_d5', 'dist_d25', 'dist_d50', 'dist_d100',
    'is_mult5', 'dist_round_to_mult5',
    'days_since_pivot', 'recency_rank',
]

# ── CV helper ──────────────────────────────────────────────────────────────────

import xgboost as xgb

N_FOLDS = 3

def _run_cv(df, label, verbose=True):
    """3-fold expanding-window CV. Returns summary dict."""
    df = _nn_relabel(df)
    n_pos = df['label'].sum()
    n_total = len(df)

    feat_cols = [c for c in FEATURE_COLS if c in df.columns]
    X = df[feat_cols].values.astype(np.float32)
    y = df['label'].values
    dates = df['trading_date'].values
    unique_dates = sorted(df['trading_date'].unique())

    candidates_per_day = n_total / max(len(unique_dates), 1)
    pos_per_day = n_pos / max(len(unique_dates), 1)

    if verbose:
        print(f"\n{'='*60}")
        print(f"Config: {label}")
        print(f"  Rows: {n_total:,}  |  Candidates/day: {candidates_per_day:.0f}  "
              f"|  Positive rate: {n_pos/n_total*100:.1f}%  ({pos_per_day:.1f}/day)")

    fold_size = len(unique_dates) // N_FOLDS
    fold_results = []

    for fold in range(1, N_FOLDS + 1):
        test_start = fold_size * fold
        test_end   = min(fold_size * (fold + 1), len(unique_dates))
        if test_end <= test_start:
            continue

        train_dates_f = set(unique_dates[:test_start])
        test_dates_f  = set(unique_dates[test_start:test_end])

        tr_mask = np.array([d in train_dates_f for d in dates])
        te_mask = np.array([d in test_dates_f  for d in dates])

        X_tr, y_tr = X[tr_mask], y[tr_mask]
        X_te, y_te = X[te_mask], y[te_mask]

        scale_pos = (y_tr == 0).sum() / max((y_tr == 1).sum(), 1)

        m = xgb.XGBClassifier(
            n_estimators=400, max_depth=5, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8,
            scale_pos_weight=scale_pos,
            eval_metric='logloss', random_state=42, n_jobs=-1,
        )
        m.fit(X_tr, y_tr, eval_set=[(X_te, y_te)], verbose=False)

        probs = m.predict_proba(X_te)[:, 1]
        test_dates_sorted = sorted(test_dates_f)

        if verbose:
            print(f"  Fold {fold}: train={len(train_dates_f)}d  test={len(test_dates_f)}d  "
                  f"({min(test_dates_sorted)} to {max(test_dates_sorted)})")

        for thr in [0.30, 0.40, 0.50]:
            pred = (probs >= thr).astype(int)
            tp = ((pred==1)&(y_te==1)).sum()
            fp = ((pred==1)&(y_te==0)).sum()
            fn = ((pred==0)&(y_te==1)).sum()
            prec = tp/(tp+fp) if (tp+fp) else 0
            rec  = tp/(tp+fn) if (tp+fn) else 0
            f1   = 2*prec*rec/(prec+rec) if (prec+rec) else 0
            lpd  = pred.sum()/len(test_dates_sorted)
            fold_results.append({
                'config': label, 'fold': fold, 'threshold': thr,
                'prec': round(prec*100,1), 'rec': round(rec*100,1),
                'f1': round(f1*100,1), 'levels_per_day': round(lpd,1),
            })
            if verbose:
                print(f"    thr={thr:.2f}  prec={prec*100:.1f}%  rec={rec*100:.1f}%  "
                      f"f1={f1*100:.1f}%  levels/day={lpd:.1f}")

    # Feature importance on final model (all data)
    scale_pos_all = (y == 0).sum() / max((y == 1).sum(), 1)
    final_model = xgb.XGBClassifier(
        n_estimators=400, max_depth=5, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8,
        scale_pos_weight=scale_pos_all,
        eval_metric='logloss', random_state=42, n_jobs=-1,
    )
    final_model.fit(X, y, verbose=False)

    fi = pd.DataFrame({
        'feature':    feat_cols,
        'importance': final_model.feature_importances_,
    }).sort_values('importance', ascending=False)

    if verbose:
        print(f"\n  Feature importance ({label}):")
        for _, row in fi.head(8).iterrows():
            print(f"    {row['feature']:25s}  {row['importance']:.4f}")

    # Save model
    model_path = ROOT / 'data' / f"phase6c_{label.replace(' ','_').replace('/','p')}_model.json"
    final_model.save_model(str(model_path))

    return fold_results, fi, candidates_per_day, n_pos/n_total*100


# ── Run all configurations ─────────────────────────────────────────────────────

from data_manager import warm_cache
from feature_builder import build_feature_matrix

print("Warming cache...")
warm_cache()

configs = [
    # (label, max_pivot_age_days, top_n_per_window)
    ('baseline',          None, None),
    ('recency_365d',      365,  None),
    ('recency_180d',      180,  None),
    ('sig_top50',         None, 50),
    ('sig_top30',         None, 30),
    ('rec365_sig50',      365,  50),
    ('rec180_sig30',      180,  30),
]

all_fold_results = []
summary_rows     = []
feature_importances = {}

for (label, max_age, top_n) in configs:
    feat_path = ROOT / 'data' / f"phase6c_{label}_features.parquet"
    if feat_path.exists():
        print(f"\nLoading {feat_path} ...")
        df = pd.read_parquet(feat_path)
    else:
        print(f"\nBuilding feature matrix: {label}  "
              f"(max_age={max_age}d  top_n={top_n}) ...")
        df = build_feature_matrix(verbose=False,
                                  max_pivot_age_days=max_age,
                                  top_n_per_window=top_n)
        df.to_parquet(feat_path, index=False)
        print(f"  Saved: {feat_path}")

    fold_res, fi, cand_day, pos_rate = _run_cv(df, label, verbose=True)
    all_fold_results.extend(fold_res)
    feature_importances[label] = fi
    summary_rows.append({
        'config':          label,
        'max_age_days':    max_age if max_age else 'none',
        'top_n':           top_n   if top_n   else 'none',
        'candidates/day':  round(cand_day, 0),
        'pos_rate%':       round(pos_rate, 1),
    })

# ── Summary ────────────────────────────────────────────────────────────────────

df_folds = pd.DataFrame(all_fold_results)
print("\n" + "="*60)
print("CV Summary (avg across folds, thr=0.50):")
summary_50 = (df_folds[df_folds['threshold'] == 0.50]
              .groupby('config')[['prec','rec','f1','levels_per_day']]
              .mean().round(1))
print(summary_50.to_string())

print("\nPool stats by config:")
df_pool = pd.DataFrame(summary_rows)
print(df_pool.to_string(index=False))

# ── Write Excel ────────────────────────────────────────────────────────────────

OUT_PATH = ROOT / 'data' / 'auto_levels_analysis.xlsx'
existing = {}
with pd.ExcelFile(OUT_PATH, engine='openpyxl') as xf:
    for sn in xf.sheet_names:
        existing[sn] = pd.read_excel(xf, sheet_name=sn)

from openpyxl.utils import get_column_letter

def _autofit(sheet):
    for col in sheet.columns:
        w = max((len(str(c.value)) for c in col if c.value is not None), default=10)
        sheet.column_dimensions[get_column_letter(col[0].column)].width = min(w+2, 50)

with pd.ExcelWriter(OUT_PATH, engine='openpyxl') as writer:
    for sn, d in existing.items():
        d.to_excel(writer, sheet_name=sn, index=False)

    df_folds.to_excel(writer, sheet_name='P6c CV Folds', index=False)
    summary_50.reset_index().to_excel(writer, sheet_name='P6c CV Summary thr0.5', index=False)
    df_pool.to_excel(writer, sheet_name='P6c Pool Stats', index=False)

    # One sheet per config's feature importance
    for cfg_label, fi_df in feature_importances.items():
        sheet_name = f'P6c FI {cfg_label[:18]}'
        fi_df.to_excel(writer, sheet_name=sheet_name, index=False)

    for sheet in writer.sheets.values():
        _autofit(sheet)

print(f"\nWritten: {OUT_PATH}")
