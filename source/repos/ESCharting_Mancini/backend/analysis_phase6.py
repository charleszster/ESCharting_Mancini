"""
Phase 6: ML pivot quality classifier.

Trains an XGBoost binary classifier on the feature matrix from feature_builder.py.
Labels: 1 = candidate matches a Mancini level within ±2pts, 0 = doesn't.

Validation: time-series walk-forward (train on first 80% of dates, test on last 20%).
No data leakage -- test dates are strictly after all training dates.

Outputs:
  - Feature importance table (printed + Excel sheet)
  - Precision / recall at various score thresholds
  - Per-day comparison: our rule-based vs ML-scored levels vs Mancini
  - Saved model: data/phase6_model.json
"""

import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).parent.parent

# -- load or build feature matrix ----------------------------------------------

FEAT_PATH = ROOT / 'data' / 'phase6_features.parquet'

if FEAT_PATH.exists():
    print(f"Loading feature matrix from {FEAT_PATH} ...")
    df = pd.read_parquet(FEAT_PATH)
else:
    from data_manager import warm_cache
    print("Feature matrix not found -- building now ...")
    warm_cache()
    from feature_builder import build_feature_matrix
    df = build_feature_matrix(verbose=True)
    df.to_parquet(FEAT_PATH, index=False)
    print(f"Saved: {FEAT_PATH}")

print(f"Rows: {len(df):,}  |  Raw positive rate: {df['label'].mean()*100:.1f}%")
print(f"Date range: {df['trading_date'].min()} to {df['trading_date'].max()}")
print(f"Unique dates: {df['trading_date'].nunique()}")

# -- re-label with nearest-neighbour assignment ---------------------------------
# The raw label marks ALL candidates within ±2pts of any Mancini level as positive.
# On dense/ranging days this produces 60-70% positive rates -- too noisy for ML.
# Fix: for each Mancini level, only the SINGLE closest candidate within ±2pts
# gets label=1. All others are 0. This gives clean 1-to-1 matching.

import sqlite3, re as _re

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

conn = sqlite3.connect(ROOT / 'data' / 'levels.db')
man_rows = conn.execute(
    "SELECT trading_date, supports, resistances FROM levels "
    "WHERE trading_date >= '2025-03-07' ORDER BY trading_date"
).fetchall()
conn.close()
man_by_date = {td: _parse_man(ms) + _parse_man(mr) for td, ms, mr in man_rows}

MATCH_TOL = 2.0
nn_labels = np.zeros(len(df), dtype=np.int8)
dates_arr = df['trading_date'].values
prices_arr = df['price'].values

for td, man_levels in man_by_date.items():
    if not man_levels:
        continue
    day_idx = np.where(dates_arr == td)[0]
    if len(day_idx) == 0:
        continue
    day_prices = prices_arr[day_idx]
    for ml in man_levels:
        dists = np.abs(day_prices - ml)
        best_i = dists.argmin()
        if dists[best_i] <= MATCH_TOL:
            nn_labels[day_idx[best_i]] = 1

df['label'] = nn_labels
n_pos = df['label'].sum()
print(f"After nearest-neighbour relabelling: {n_pos:,} positives "
      f"({n_pos/len(df)*100:.1f}%)  avg {n_pos/df['trading_date'].nunique():.1f}/day")

# -- feature columns ------------------------------------------------------------

FEATURE_COLS = [
    'pivot_type', 'is_support',
    'bounce', 'touches', 'local_density', 'prominence',
    'vol_zscore', 'consolidation', 'clean_departure',
    'dist_from_4pm', 'dist_d5', 'dist_d25', 'dist_d50', 'dist_d100',
    'days_since_pivot', 'recency_rank',
]

X = df[FEATURE_COLS].values
y = df['label'].values
dates = df['trading_date'].values

# -- time-series train/test split -----------------------------------------------

unique_dates = sorted(df['trading_date'].unique())
n_train = int(len(unique_dates) * 0.80)
train_dates = set(unique_dates[:n_train])
test_dates  = set(unique_dates[n_train:])

train_mask = np.array([d in train_dates for d in dates])
test_mask  = np.array([d in test_dates  for d in dates])

X_train, y_train = X[train_mask], y[train_mask]
X_test,  y_test  = X[test_mask],  y[test_mask]

print(f"\nTrain: {n_train} dates ({train_mask.sum():,} rows, {y_train.mean()*100:.1f}% positive)")
print(f"Test:  {len(unique_dates)-n_train} dates ({test_mask.sum():,} rows, {y_test.mean()*100:.1f}% positive)")

# -- train XGBoost --------------------------------------------------------------

try:
    import xgboost as xgb
except ImportError:
    raise SystemExit("xgboost not installed. Run: pip install xgboost")

scale_pos = (y_train == 0).sum() / max((y_train == 1).sum(), 1)
print(f"\nscale_pos_weight: {scale_pos:.1f}  (class imbalance correction)")

model = xgb.XGBClassifier(
    n_estimators=400,
    max_depth=5,
    learning_rate=0.05,
    subsample=0.8,
    colsample_bytree=0.8,
    scale_pos_weight=scale_pos,
    eval_metric='logloss',
    random_state=42,
    n_jobs=-1,
)

print("Training...")
model.fit(
    X_train, y_train,
    eval_set=[(X_test, y_test)],
    verbose=50,
)

# -- feature importance ---------------------------------------------------------

fi = pd.DataFrame({
    'feature':    FEATURE_COLS,
    'importance': model.feature_importances_,
}).sort_values('importance', ascending=False)

print("\n--- Feature Importance ---")
print(fi.to_string(index=False))

# threshold sweep

probs_test = model.predict_proba(X_test)[:, 1]
df_test = df[test_mask].copy()
df_test['score'] = probs_test

print("\n--- Threshold sweep (test set) ---")
print(f"{'threshold':>10} {'prec':>8} {'rec':>8} {'f1':>8} {'levels/day':>12}")

thresh_rows = []
test_dates_sorted = sorted(test_dates)
for thr in [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50]:
    predicted = (probs_test >= thr).astype(int)
    tp = ((predicted == 1) & (y_test == 1)).sum()
    fp = ((predicted == 1) & (y_test == 0)).sum()
    fn = ((predicted == 0) & (y_test == 1)).sum()
    prec = tp / (tp + fp) if (tp + fp) > 0 else 0
    rec  = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1   = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0
    n_per_day = predicted.sum() / max(len(test_dates_sorted), 1)
    print(f"{thr:>10.2f} {prec*100:>7.1f}% {rec*100:>7.1f}% {f1*100:>7.1f}% {n_per_day:>12.1f}")
    thresh_rows.append({'threshold': thr, 'precision': round(prec*100,1),
                        'recall': round(rec*100,1), 'f1': round(f1*100,1),
                        'levels_per_day': round(n_per_day,1)})

df_thresh = pd.DataFrame(thresh_rows)

# -- per-day recall comparison: rule-based vs ML --------------------------------
# Rule-based accepted candidates are those that survive dedup in auto_levels.py.
# Here we approximate: use score >= best_f1_threshold as the ML selector,
# and compare vs Mancini recall.

best_thr_row = df_thresh.loc[df_thresh['f1'].idxmax()]
best_thr = float(best_thr_row['threshold'])
print(f"\nBest F1 threshold: {best_thr}  "
      f"prec={best_thr_row['precision']}%  rec={best_thr_row['recall']}%  "
      f"levels/day={best_thr_row['levels_per_day']}")

# Per-date recall on test set
df_test['ml_pick'] = (df_test['score'] >= best_thr).astype(int)
per_day = []
for td in test_dates_sorted:
    day = df_test[df_test['trading_date'] == td]
    pos = day[day['label'] == 1]
    n_man = len(pos)
    if n_man == 0:
        continue
    ml_rec  = day[day['ml_pick'] == 1]['label'].sum() / n_man
    per_day.append({'date': td, 'n_mancini': n_man,
                    'ml_recall': round(ml_rec * 100, 1),
                    'ml_levels': day['ml_pick'].sum()})

df_per_day = pd.DataFrame(per_day)
print(f"\nTest-set per-day stats (threshold={best_thr}):")
print(f"  Avg ML recall:  {df_per_day['ml_recall'].mean():.1f}%")
print(f"  Avg ML levels/day: {df_per_day['ml_levels'].mean():.1f}")
print(f"  Avg Mancini levels/day: {df_per_day['n_mancini'].mean():.1f}")

# -- save model -----------------------------------------------------------------

model_path = ROOT / 'data' / 'phase6_model.json'
model.save_model(str(model_path))
print(f"\nModel saved: {model_path}")

# -- write Excel ----------------------------------------------------------------

OUT_PATH = ROOT / 'data' / 'auto_levels_analysis.xlsx'
existing = {}
with pd.ExcelFile(OUT_PATH, engine='openpyxl') as xf:
    for sn in xf.sheet_names:
        existing[sn] = pd.read_excel(xf, sheet_name=sn)

from openpyxl.utils import get_column_letter

def _autofit(sheet):
    for col in sheet.columns:
        w = max((len(str(c.value)) for c in col if c.value is not None), default=10)
        sheet.column_dimensions[get_column_letter(col[0].column)].width = min(w + 2, 50)

with pd.ExcelWriter(OUT_PATH, engine='openpyxl') as writer:
    for sn, d in existing.items():
        d.to_excel(writer, sheet_name=sn, index=False)
    fi.to_excel(writer, sheet_name='P6 Feature Importance', index=False)
    df_thresh.to_excel(writer, sheet_name='P6 Threshold Sweep', index=False)
    df_per_day.to_excel(writer, sheet_name='P6 Per-Day Recall', index=False)
    for sheet in writer.sheets.values():
        _autofit(sheet)

print(f"Written: {OUT_PATH}")
