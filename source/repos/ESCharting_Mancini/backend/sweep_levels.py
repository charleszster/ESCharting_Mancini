"""
1. Systematic miss analysis
2. One-at-a-time parameter sensitivity sweep
Run from the backend directory: python sweep_levels.py
"""
import sys, re, sqlite3
import pandas as pd
import numpy as np
from pathlib import Path
from copy import deepcopy

ROOT = Path(__file__).parent.parent

from data_manager import warm_cache, _get_cache
from auto_levels import compute_auto_levels, _resample_15m, _find_4pm_bar

MATCH_TOL = 2.0
DATE_FROM  = "2025-12-10"

BASE_PARAMS = dict(
    pivot_len        = 5,
    price_range      = 250.0,
    min_spacing      = 3.0,
    touch_zone       = 2.0,
    maj_bounce       = 40.0,
    maj_touches      = 5,
    forward_bars     = 100,
    show_major_only  = False,
    show_supports    = True,
    show_resistances = True,
)

# ── warm cache ─────────────────────────────────────────────────────────────────
print("Warming cache ...")
warm_cache()
print("Cache ready.")

# ── Mancini parser ─────────────────────────────────────────────────────────────
def _parse_price_token(tok):
    tok = tok.strip().strip(',')
    m = re.match(r'^(\d+)-(\d+)$', tok)
    if m:
        a, b_raw = m.group(1), m.group(2)
        b = (a[:len(a)-len(b_raw)] + b_raw) if len(b_raw) < len(a) else b_raw
        return (float(a) + float(b)) / 2
    return float(tok)

def parse_mancini(text):
    if not text:
        return []
    clean = re.sub(r'\s*\(major\)', '', text)
    out = []
    for part in clean.split(','):
        part = part.strip()
        if part:
            try: out.append(_parse_price_token(part))
            except: pass
    return sorted(out)

# ── load DB ────────────────────────────────────────────────────────────────────
conn = sqlite3.connect(ROOT / "data" / "levels.db")
rows = conn.execute(
    "SELECT trading_date, supports, resistances FROM levels "
    "WHERE trading_date >= ? ORDER BY trading_date", (DATE_FROM,)
).fetchall()
conn.close()

# also get close4pm for each date (for distance analysis)
df_cache = _get_cache()
df15 = _resample_15m(df_cache)

mancini = {}
close4pm_map = {}
for td, ms, mr in rows:
    mancini[td] = {'sup': parse_mancini(ms), 'res': parse_mancini(mr)}
    c4, _ = _find_4pm_bar(df15, td)
    close4pm_map[td] = c4

dates = list(mancini.keys())
print(f"Dates: {len(dates)}")

# ── helpers ────────────────────────────────────────────────────────────────────
def count_matches(a, b, tol=MATCH_TOL):
    if not a or not b:
        return 0
    b_arr = np.array(b)
    return sum(1 for p in a if np.min(np.abs(b_arr - p)) <= tol)

def run_params(params, dates_list=None):
    """Run auto_levels for all dates, return DataFrame of per-day stats."""
    if dates_list is None:
        dates_list = dates
    rows_out = []
    for td in dates_list:
        try:
            r = compute_auto_levels(target_date=td, **params)
        except Exception:
            continue
        os_ = [l['price'] for l in r['supports']]
        or_ = [l['price'] for l in r['resistances']]
        ms_ = mancini[td]['sup']
        mr_ = mancini[td]['res']
        c4  = close4pm_map[td]
        rows_out.append({
            'date':      td,
            'close4pm':  c4,
            'n_our_sup': len(os_), 'n_man_sup': len(ms_),
            'n_our_res': len(or_), 'n_man_res': len(mr_),
            'sup_prec':  count_matches(os_, ms_)/len(os_)*100 if os_ else None,
            'sup_rec':   count_matches(ms_, os_)/len(ms_)*100 if ms_ else None,
            'res_prec':  count_matches(or_, mr_)/len(or_)*100 if or_ else None,
            'res_rec':   count_matches(mr_, or_)/len(mr_)*100 if mr_ else None,
            'our_sup':   os_, 'our_res': or_,
            'man_sup':   ms_, 'man_res': mr_,
        })
    df = pd.DataFrame(rows_out)
    return df

def summary(df):
    tot_os = df['n_our_sup'].sum(); tot_ms = df['n_man_sup'].sum()
    tot_or = df['n_our_res'].sum(); tot_mr = df['n_man_res'].sum()
    hit_os = sum(count_matches(r['our_sup'], r['man_sup']) for _, r in df.iterrows())
    hit_ms = sum(count_matches(r['man_sup'], r['our_sup']) for _, r in df.iterrows())
    hit_or = sum(count_matches(r['our_res'], r['man_res']) for _, r in df.iterrows())
    hit_mr = sum(count_matches(r['man_res'], r['our_res']) for _, r in df.iterrows())
    return {
        'sup_prec': hit_os/tot_os*100 if tot_os else 0,
        'sup_rec':  hit_ms/tot_ms*100 if tot_ms else 0,
        'res_prec': hit_or/tot_or*100 if tot_or else 0,
        'res_rec':  hit_mr/tot_mr*100 if tot_mr else 0,
        'avg_our':  (tot_os+tot_or)/len(df),
        'avg_man':  (tot_ms+tot_mr)/len(df),
    }

# ════════════════════════════════════════════════════════════════════════
# PART 1 — Systematic miss analysis
# ════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("PART 1: Systematic miss analysis (baseline params)")
print("="*60)

df_base = run_params(BASE_PARAMS)

# --- 1a: Performance by month ---
df_base['month'] = pd.to_datetime(df_base['date']).dt.to_period('M')
print("\nPerformance by month:")
monthly = df_base.groupby('month').agg(
    days=('date','count'),
    sup_prec=('sup_prec','mean'), sup_rec=('sup_rec','mean'),
    res_prec=('res_prec','mean'), res_rec=('res_rec','mean'),
).round(1)
print(monthly.to_string())

# --- 1b: Miss distance analysis ---
# For each Mancini level NOT captured, what's its distance from close4pm?
missed_sup_dists, missed_res_dists = [], []
matched_sup_dists, matched_res_dists = [], []

for _, row in df_base.iterrows():
    c4 = row['close4pm']
    if not c4:
        continue
    b_sup = np.array(row['our_sup']) if row['our_sup'] else np.array([])
    b_res = np.array(row['our_res']) if row['our_res'] else np.array([])

    for p in row['man_sup']:
        dist = abs(p - c4)
        if len(b_sup) > 0 and np.min(np.abs(b_sup - p)) <= MATCH_TOL:
            matched_sup_dists.append(dist)
        else:
            missed_sup_dists.append(dist)

    for p in row['man_res']:
        dist = abs(p - c4)
        if len(b_res) > 0 and np.min(np.abs(b_res - p)) <= MATCH_TOL:
            matched_res_dists.append(dist)
        else:
            missed_res_dists.append(dist)

print("\nMissed Mancini supports — distance from 4pm close (percentiles):")
if missed_sup_dists:
    arr = np.array(missed_sup_dists)
    print(f"  n={len(arr)}  p25={np.percentile(arr,25):.1f}  median={np.median(arr):.1f}  p75={np.percentile(arr,75):.1f}  p90={np.percentile(arr,90):.1f}  max={arr.max():.1f}")
    print(f"  % within 50pts: {(arr<=50).mean()*100:.1f}%")
    print(f"  % within 100pts: {(arr<=100).mean()*100:.1f}%")
    print(f"  % within 150pts: {(arr<=150).mean()*100:.1f}%")
    print(f"  % within 200pts: {(arr<=200).mean()*100:.1f}%")

print("\nMatched Mancini supports — distance from 4pm close (percentiles):")
if matched_sup_dists:
    arr = np.array(matched_sup_dists)
    print(f"  n={len(arr)}  p25={np.percentile(arr,25):.1f}  median={np.median(arr):.1f}  p75={np.percentile(arr,75):.1f}  p90={np.percentile(arr,90):.1f}  max={arr.max():.1f}")

print("\nMissed Mancini resistances — distance from 4pm close (percentiles):")
if missed_res_dists:
    arr = np.array(missed_res_dists)
    print(f"  n={len(arr)}  p25={np.percentile(arr,25):.1f}  median={np.median(arr):.1f}  p75={np.percentile(arr,75):.1f}  p90={np.percentile(arr,90):.1f}  max={arr.max():.1f}")
    print(f"  % within 50pts: {(arr<=50).mean()*100:.1f}%")
    print(f"  % within 100pts: {(arr<=100).mean()*100:.1f}%")
    print(f"  % within 150pts: {(arr<=150).mean()*100:.1f}%")
    print(f"  % within 200pts: {(arr<=200).mean()*100:.1f}%")

print("\nMatched Mancini resistances — distance from 4pm close (percentiles):")
if matched_res_dists:
    arr = np.array(matched_res_dists)
    print(f"  n={len(arr)}  p25={np.percentile(arr,25):.1f}  median={np.median(arr):.1f}  p75={np.percentile(arr,75):.1f}  p90={np.percentile(arr,90):.1f}  max={arr.max():.1f}")

# --- 1c: Our phantom levels — where are they? ---
print("\n--- Our phantom levels (not in Mancini) ---")
phantom_sup_dists, phantom_res_dists = [], []
for _, row in df_base.iterrows():
    c4 = row['close4pm']
    if not c4:
        continue
    b_ms = np.array(row['man_sup']) if row['man_sup'] else np.array([])
    b_mr = np.array(row['man_res']) if row['man_res'] else np.array([])
    for p in row['our_sup']:
        if len(b_ms) == 0 or np.min(np.abs(b_ms - p)) > MATCH_TOL:
            phantom_sup_dists.append(abs(p - c4))
    for p in row['our_res']:
        if len(b_mr) == 0 or np.min(np.abs(b_mr - p)) > MATCH_TOL:
            phantom_res_dists.append(abs(p - c4))

print(f"Phantom supports (n={len(phantom_sup_dists)}):")
if phantom_sup_dists:
    arr = np.array(phantom_sup_dists)
    print(f"  p25={np.percentile(arr,25):.1f}  median={np.median(arr):.1f}  p75={np.percentile(arr,75):.1f}  p90={np.percentile(arr,90):.1f}")

print(f"Phantom resistances (n={len(phantom_res_dists)}):")
if phantom_res_dists:
    arr = np.array(phantom_res_dists)
    print(f"  p25={np.percentile(arr,25):.1f}  median={np.median(arr):.1f}  p75={np.percentile(arr,75):.1f}  p90={np.percentile(arr,90):.1f}")

# --- 1d: Level count comparison ---
print("\n--- Level count mismatch analysis ---")
df_base['sup_count_ratio'] = df_base['n_our_sup'] / df_base['n_man_sup'].clip(lower=1)
df_base['res_count_ratio'] = df_base['n_our_res'] / df_base['n_man_res'].clip(lower=1)
print(f"Our sup / Mancini sup ratio: mean={df_base['sup_count_ratio'].mean():.2f}  median={df_base['sup_count_ratio'].median():.2f}")
print(f"Our res / Mancini res ratio: mean={df_base['res_count_ratio'].mean():.2f}  median={df_base['res_count_ratio'].median():.2f}")
print(f"Days we over-generate supports (ratio>1.5): {(df_base['sup_count_ratio']>1.5).sum()}")
print(f"Days we under-generate supports (ratio<0.7): {(df_base['sup_count_ratio']<0.7).sum()}")
print(f"Days we over-generate resistances (ratio>1.5): {(df_base['res_count_ratio']>1.5).sum()}")
print(f"Days we under-generate resistances (ratio<0.7): {(df_base['res_count_ratio']<0.7).sum()}")

# --- 1e: Feb 9 anomaly ---
print("\n--- 2026-02-09 anomaly (0% sup precision) ---")
r09 = df_base[df_base['date']=='2026-02-09'].iloc[0]
print(f"  close4pm={r09['close4pm']}")
print(f"  Our supports (first 10): {sorted(r09['our_sup'])[:10]}")
print(f"  Mancini supports (first 10): {sorted(r09['man_sup'])[:10]}")

# ════════════════════════════════════════════════════════════════════════
# PART 2 — One-at-a-time parameter sweep
# ════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("PART 2: One-at-a-time parameter sensitivity sweep")
print("="*60)

SWEEPS = {
    'pivot_len':    [3, 4, 5, 6, 7, 8, 10],
    'min_spacing':  [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0],
    'price_range':  [150.0, 200.0, 250.0, 300.0, 350.0],
    'forward_bars': [50, 75, 100, 150, 200],
    'maj_bounce':   [20.0, 30.0, 40.0, 50.0, 60.0],
    'maj_touches':  [3, 4, 5, 6, 7],
    'show_major_only': [False, True],
}

sweep_results = []
total_runs = sum(len(v) for v in SWEEPS.values())
run_i = 0

for param_name, values in SWEEPS.items():
    for val in values:
        run_i += 1
        p = deepcopy(BASE_PARAMS)
        p[param_name] = val
        print(f"  [{run_i}/{total_runs}] {param_name}={val}", end='\r', flush=True)
        df_run = run_params(p)
        s = summary(df_run)
        sweep_results.append({
            'param':      param_name,
            'value':      val,
            'is_base':    (val == BASE_PARAMS[param_name]),
            'sup_prec':   round(s['sup_prec'], 1),
            'sup_rec':    round(s['sup_rec'], 1),
            'res_prec':   round(s['res_prec'], 1),
            'res_rec':    round(s['res_rec'], 1),
            'avg_our':    round(s['avg_our'], 1),
            'avg_man':    round(s['avg_man'], 1),
        })

print(f"\nSweep done — {run_i} runs.")
df_sweep = pd.DataFrame(sweep_results)

print("\nSweep results:")
print(df_sweep.to_string(index=False))

# ════════════════════════════════════════════════════════════════════════
# PART 3 — Write to Excel (new sheets in same file)
# ════════════════════════════════════════════════════════════════════════
OUT_PATH = ROOT / "data" / "auto_levels_analysis.xlsx"
print(f"\nWriting sweep results to {OUT_PATH} ...")

# Read existing sheets
existing = {}
with pd.ExcelFile(OUT_PATH, engine='openpyxl') as xf:
    for sn in xf.sheet_names:
        existing[sn] = pd.read_excel(xf, sheet_name=sn)

# Monthly summary for analysis
monthly_df = df_base.groupby('month').agg(
    days=('date','count'),
    avg_our_sup=('n_our_sup','mean'), avg_man_sup=('n_man_sup','mean'),
    avg_our_res=('n_our_res','mean'), avg_man_res=('n_man_res','mean'),
    sup_prec=('sup_prec','mean'), sup_rec=('sup_rec','mean'),
    res_prec=('res_prec','mean'), res_rec=('res_rec','mean'),
).round(1).reset_index()
monthly_df['month'] = monthly_df['month'].astype(str)

from openpyxl.utils import get_column_letter

with pd.ExcelWriter(OUT_PATH, engine='openpyxl') as writer:
    for sn, df_ in existing.items():
        df_.to_excel(writer, sheet_name=sn, index=False)
    monthly_df.to_excel(writer, sheet_name='Monthly Breakdown', index=False)
    df_sweep.to_excel(writer, sheet_name='Param Sweep', index=False)

    for sheet in writer.sheets.values():
        for col in sheet.columns:
            max_len = max((len(str(c.value)) for c in col if c.value is not None), default=10)
            sheet.column_dimensions[get_column_letter(col[0].column)].width = min(max_len + 2, 80)

print(f"Done. Written: {OUT_PATH}")
