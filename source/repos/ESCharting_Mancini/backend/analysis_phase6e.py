"""
Phase 6e: ML on deduplicated candidate pool.

Key insight from Phases 6a-6d:
  - Raw pool: ~825 candidates/day, 6.8% base rate => precision ceiling 18%
  - Significance pre-filter: breaks ceiling but discards 41% of Mancini's levels
  - Better approach: use auto_levels.py dedup output as candidate pool
    (~100 levels/day, ~55% base rate) => precision ceiling should be 70-80%+

The dedup step (min_spacing=3.0, newest-first) already does the hard work of
collapsing clusters into single representatives. ML just needs to score those
~100 and pick the best ~55 to match Mancini.

This keeps us on Path A (matching Mancini's system) without sacrificing recall.
"""

import numpy as np
import pandas as pd
import sqlite3, re as _re
from pathlib import Path

ROOT = Path(__file__).parent.parent
MATCH_TOL = 2.0

# ── Mancini relabelling ────────────────────────────────────────────────────────

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
    prices_arr = df['price_rounded'].values

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

# ── Load or build feature matrix ───────────────────────────────────────────────

from data_manager import warm_cache
from feature_builder import build_feature_matrix_deduped

FEAT_PATH = ROOT / 'data' / 'phase6e_features.parquet'

print("Warming cache...")
warm_cache()

if FEAT_PATH.exists():
    print(f"Loading {FEAT_PATH} ...")
    df = pd.read_parquet(FEAT_PATH)
else:
    print("Building deduplicated feature matrix ...")
    df = build_feature_matrix_deduped(verbose=True)
    df.to_parquet(FEAT_PATH, index=False)
    print(f"Saved: {FEAT_PATH}")

print(f"\nRows: {len(df):,}  |  Raw positive rate: {df['label'].mean()*100:.1f}%")
print(f"Dates: {df['trading_date'].nunique()}  "
      f"({df['trading_date'].min()} to {df['trading_date'].max()})")

# ── Nearest-neighbour relabelling ──────────────────────────────────────────────

df = _nn_relabel(df)
n_pos = df['label'].sum()
unique_dates = sorted(df['trading_date'].unique())
print(f"After NN relabelling: {n_pos:,} positives ({n_pos/len(df)*100:.1f}%)  "
      f"avg {n_pos/len(unique_dates):.1f}/day")
print(f"Avg candidates/day: {len(df)/len(unique_dates):.0f}")

# ── 3-fold expanding-window CV ────────────────────────────────────────────────

import xgboost as xgb

feat_cols = [c for c in FEATURE_COLS if c in df.columns]
X = df[feat_cols].values.astype(np.float32)
y = df['label'].values
dates = df['trading_date'].values

N_FOLDS   = 3
fold_size = len(unique_dates) // N_FOLDS
fold_results = []

print(f"\nTime-series {N_FOLDS}-fold CV ({len(unique_dates)} dates, ~{fold_size} per fold)")

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

    print(f"\n  Fold {fold}: train={len(train_dates_f)}d  test={len(test_dates_f)}d  "
          f"({min(test_dates_sorted)} to {max(test_dates_sorted)})")

    for thr in [0.30, 0.40, 0.50, 0.60]:
        pred = (probs >= thr).astype(int)
        tp = ((pred==1)&(y_te==1)).sum()
        fp = ((pred==1)&(y_te==0)).sum()
        fn = ((pred==0)&(y_te==1)).sum()
        prec = tp/(tp+fp) if (tp+fp) else 0
        rec  = tp/(tp+fn) if (tp+fn) else 0
        f1   = 2*prec*rec/(prec+rec) if (prec+rec) else 0
        lpd  = pred.sum()/len(test_dates_sorted)
        fold_results.append({'fold': fold, 'threshold': thr,
                             'prec': round(prec*100,1), 'rec': round(rec*100,1),
                             'f1': round(f1*100,1), 'levels_per_day': round(lpd,1)})
        print(f"    thr={thr:.2f}  prec={prec*100:.1f}%  rec={rec*100:.1f}%  "
              f"f1={f1*100:.1f}%  levels/day={lpd:.1f}")

# ── Train final model on all data ─────────────────────────────────────────────

print("\nTraining final model on all data ...")
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

print("\n--- Feature Importance (final model) ---")
print(fi.to_string(index=False))

# ── CV summary ────────────────────────────────────────────────────────────────

df_folds = pd.DataFrame(fold_results)
print("\n--- CV Summary (avg across folds) ---")
summary = df_folds.groupby('threshold')[['prec','rec','f1','levels_per_day']].mean().round(1)
print(summary.to_string())

# ── Save model ────────────────────────────────────────────────────────────────

model_path = ROOT / 'data' / 'phase6e_model.json'
final_model.save_model(str(model_path))
print(f"\nModel saved: {model_path}")

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
    fi.to_excel(writer, sheet_name='P6e Feature Importance', index=False)
    df_folds.to_excel(writer, sheet_name='P6e CV Folds', index=False)
    summary.reset_index().to_excel(writer, sheet_name='P6e CV Summary', index=False)
    for sheet in writer.sheets.values():
        _autofit(sheet)

print(f"Written: {OUT_PATH}")
