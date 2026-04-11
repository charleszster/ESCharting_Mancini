"""
Phase 5: 2D sweep — maj_touches × forward_bars
Goal: find combination where our major% ≈ Mancini's ~42%
Key: min_bounce=0 so forward_bars ONLY affects major/minor classification, not level inclusion
     (recall stays intact; only the solid/dashed label changes)
Base: price_range=325, min_spacing=3.0, pivot_len=5, touch_zone=2.0, maj_bounce=40.0

Also computes local_pivot_density diagnostic (pre-sweep, once):
  For each accepted level, count how many other raw pivot candidates are within ±DENSITY_ZONE pts.
  High density = ranging market context on that day.
"""
import re, sqlite3
import pandas as pd
import numpy as np
from pathlib import Path
from copy import deepcopy

ROOT = Path(__file__).parent.parent

from data_manager import warm_cache, _get_cache
from auto_levels import compute_auto_levels, _resample_15m, _find_4pm_bar, _find_pivots

MATCH_TOL    = 2.0
DATE_FROM    = "2025-03-07"   # full Mancini history (215 days)
DENSITY_ZONE = 10.0           # pts — neighbourhood radius for local_pivot_density

BASE = dict(
    pivot_len=5, price_range=325.0, min_spacing=3.0, touch_zone=2.0,
    maj_bounce=40.0, maj_touches=5, forward_bars=100, min_bounce=0.0,
    show_major_only=False, show_supports=True, show_resistances=True,
)

print("Warming cache ...")
warm_cache()
print("Cache ready.")

# ── helpers ────────────────────────────────────────────────────────────────────

def _parse_price_token(tok):
    tok = tok.strip().strip(',')
    m = re.match(r'^(\d+)-(\d+)$', tok)
    if m:
        a, b_raw = m.group(1), m.group(2)
        b = (a[:len(a)-len(b_raw)] + b_raw) if len(b_raw) < len(a) else b_raw
        return (float(a) + float(b)) / 2
    return float(tok)

def parse_mancini(text):
    if not text: return []
    clean = re.sub(r'\s*\(major\)', '', text)
    out = []
    for part in clean.split(','):
        part = part.strip()
        if part:
            try: out.append(_parse_price_token(part))
            except: pass
    return sorted(out)

def parse_mancini_with_major(text):
    if not text: return []
    out = []
    for part in text.split(','):
        part = part.strip()
        if not part: continue
        is_major = '(major)' in part
        clean = re.sub(r'\s*\(major\)', '', part).strip()
        try: out.append((_parse_price_token(clean), is_major))
        except: pass
    return out

def count_matches(a, b, tol=MATCH_TOL):
    if not a or not b: return 0
    b_arr = np.array(b)
    return sum(1 for p in a if np.min(np.abs(b_arr - p)) <= tol)

# ── load Mancini data ──────────────────────────────────────────────────────────

conn = sqlite3.connect(ROOT / "data" / "levels.db")
rows = conn.execute(
    "SELECT trading_date, supports, resistances FROM levels "
    "WHERE trading_date >= ? ORDER BY trading_date", (DATE_FROM,)
).fetchall()
conn.close()

df_cache = _get_cache()
df15 = _resample_15m(df_cache)

mancini = {}
for td, ms, mr in rows:
    try:
        c4, _ = _find_4pm_bar(df15, td)
        if c4 is None: continue
    except Exception:
        continue
    mancini[td] = {
        'sup':     parse_mancini(ms),
        'res':     parse_mancini(mr),
        'sup_maj': parse_mancini_with_major(ms),
        'res_maj': parse_mancini_with_major(mr),
    }

dates = list(mancini.keys())

man_sup_total = sum(len(mancini[d]['sup']) for d in dates)
man_res_total = sum(len(mancini[d]['res']) for d in dates)
man_sup_major = sum(sum(1 for _, m in mancini[d]['sup_maj'] if m) for d in dates)
man_res_major = sum(sum(1 for _, m in mancini[d]['res_maj'] if m) for d in dates)
print(f"Dates: {len(dates)}  |  Mancini sup major: {man_sup_major/man_sup_total*100:.1f}%  "
      f"res major: {man_res_major/man_res_total*100:.1f}%")
print(f"Target: ~42% major\n")

# ── pre-sweep: local_pivot_density diagnostic ──────────────────────────────────
# Density is a property of the raw pivot candidates (before dedup), not of the
# sweep parameters.  Compute once using BASE pivot_len and price_range.

print("Computing local_pivot_density diagnostic ...")
density_rows = []

for td in dates:
    close4pm, bar4pm_et = _find_4pm_bar(df15, td)
    if close4pm is None:
        continue

    df15_hist = df15[df15.index <= bar4pm_et]
    ph_idx, ph_p, pl_idx, pl_p = _find_pivots(
        df15_hist['high'].values, df15_hist['low'].values, BASE['pivot_len']
    )

    # All raw candidates within price_range (before any dedup)
    cand_prices = []
    for p in ph_p:
        if abs(float(p) - close4pm) <= BASE['price_range']:
            cand_prices.append(float(p))
    for p in pl_p:
        if abs(float(p) - close4pm) <= BASE['price_range']:
            cand_prices.append(float(p))

    if not cand_prices:
        continue

    arr = np.array(cand_prices)
    # local_pivot_density for each candidate = # other candidates within ±DENSITY_ZONE
    densities = [int(np.sum(np.abs(arr - p) <= DENSITY_ZONE)) - 1 for p in cand_prices]

    # Also get accepted levels with BASE params to correlate density with acceptance
    try:
        r = compute_auto_levels(target_date=td, **BASE)
    except Exception:
        r = {'supports': [], 'resistances': []}

    accepted_prices = [l['price'] for l in r['supports']] + [l['price'] for l in r['resistances']]
    if accepted_prices and cand_prices:
        acc_arr = np.array(accepted_prices)
        acc_densities = []
        for p in accepted_prices:
            d = int(np.sum(np.abs(arr - p) <= DENSITY_ZONE)) - 1
            acc_densities.append(d)
    else:
        acc_densities = []

    density_rows.append({
        'trading_date':       td,
        'n_candidates':       len(cand_prices),
        'n_accepted':         len(accepted_prices),
        'all_avg_density':    round(float(np.mean(densities)), 1),
        'all_p75_density':    round(float(np.percentile(densities, 75)), 1),
        'all_max_density':    int(np.max(densities)),
        'acc_avg_density':    round(float(np.mean(acc_densities)), 1) if acc_densities else 0,
        'acc_p75_density':    round(float(np.percentile(acc_densities, 75)), 1) if acc_densities else 0,
        'acc_max_density':    int(np.max(acc_densities)) if acc_densities else 0,
        'man_sup':            len(mancini[td]['sup']),
        'man_res':            len(mancini[td]['res']),
    })

df_density = pd.DataFrame(density_rows)
print(f"  Days: {len(df_density)}  |  "
      f"avg n_candidates: {df_density['n_candidates'].mean():.0f}  |  "
      f"avg acc_avg_density: {df_density['acc_avg_density'].mean():.1f}")

# Top ranging days (highest accepted avg density)
print("\nTop 10 highest-density days (most range-bound):")
print(df_density.nlargest(10, 'acc_avg_density')[
    ['trading_date','n_candidates','n_accepted','acc_avg_density','acc_max_density','man_sup','man_res']
].to_string(index=False))

print("\nTop 10 lowest-density days (most trending):")
print(df_density.nsmallest(10, 'acc_avg_density')[
    ['trading_date','n_candidates','n_accepted','acc_avg_density','acc_max_density','man_sup','man_res']
].to_string(index=False))

# Correlation: does Mancini use fewer levels on high-density days?
df_density['man_total'] = df_density['man_sup'] + df_density['man_res']
corr = df_density[['acc_avg_density','man_total','n_accepted']].corr()
print(f"\nCorrelation matrix (density / Mancini count / our accepted count):")
print(corr.to_string())

# ── 2D sweep ──────────────────────────────────────────────────────────────────

MAJ_TOUCHES_VALS  = [5, 8, 10, 12, 15, 20]
FORWARD_BARS_VALS = [5, 6, 7, 8, 10, 12, 16, 100]

total = len(MAJ_TOUCHES_VALS) * len(FORWARD_BARS_VALS)
done  = 0
results = []

print(f"\nRunning {total}-combo sweep over {len(dates)} days ...")

for mt in MAJ_TOUCHES_VALS:
    for fb in FORWARD_BARS_VALS:
        done += 1
        print(f"  [{done:3d}/{total}] maj_touches={mt:2d}  forward_bars={fb:3d} ({fb*15}min)", end='\r', flush=True)

        p = deepcopy(BASE)
        p['maj_touches']  = mt
        p['forward_bars'] = fb

        rows_out = []
        for td in dates:
            try:
                r = compute_auto_levels(target_date=td, **p)
            except Exception:
                continue
            sups = r['supports']
            ress = r['resistances']
            os_  = [l['price'] for l in sups]
            or_  = [l['price'] for l in ress]
            ms_  = mancini[td]['sup']
            mr_  = mancini[td]['res']
            rows_out.append({
                'n_our_sup':     len(os_),
                'n_man_sup':     len(ms_),
                'n_our_res':     len(or_),
                'n_man_res':     len(mr_),
                'our_sup_major': sum(1 for l in sups if l.get('major')),
                'our_res_major': sum(1 for l in ress if l.get('major')),
                'our_sup': os_, 'our_res': or_,
                'man_sup': ms_, 'man_res': mr_,
            })

        df_r = pd.DataFrame(rows_out)
        tot_os = df_r['n_our_sup'].sum()
        tot_or = df_r['n_our_res'].sum()
        tot_ms = df_r['n_man_sup'].sum()
        tot_mr = df_r['n_man_res'].sum()

        hit_ms = sum(count_matches(r.man_sup, r.our_sup) for r in df_r.itertuples())
        hit_mr = sum(count_matches(r.man_res, r.our_res) for r in df_r.itertuples())
        hit_os = sum(count_matches(r.our_sup, r.man_sup) for r in df_r.itertuples())
        hit_or = sum(count_matches(r.our_res, r.man_res) for r in df_r.itertuples())

        sup_maj_pct = df_r['our_sup_major'].sum() / tot_os * 100 if tot_os else 0
        res_maj_pct = df_r['our_res_major'].sum() / tot_or * 100 if tot_or else 0

        results.append({
            'maj_touches':   mt,
            'forward_bars':  fb,
            'window_min':    fb * 15,
            'sup_rec':       round(hit_ms / tot_ms * 100, 1) if tot_ms else 0,
            'sup_prec':      round(hit_os / tot_os * 100, 1) if tot_os else 0,
            'res_rec':       round(hit_mr / tot_mr * 100, 1) if tot_mr else 0,
            'res_prec':      round(hit_or / tot_or * 100, 1) if tot_or else 0,
            'avg_our_total': round((tot_os + tot_or) / len(df_r), 1),
            'our_sup_maj%':  round(sup_maj_pct, 1),
            'our_res_maj%':  round(res_maj_pct, 1),
        })

print()

# ── print sweep results ────────────────────────────────────────────────────────

df_res = pd.DataFrame(results)
print(df_res.to_string(index=False))

df_res['sup_maj_err'] = (df_res['our_sup_maj%'] - 42).abs()
best = df_res.nsmallest(5, 'sup_maj_err')[
    ['maj_touches','forward_bars','sup_rec','our_sup_maj%','our_res_maj%','sup_maj_err']
]
print("\nTop 5 rows closest to 42% sup_major:")
print(best.to_string(index=False))

# ── write to Excel ─────────────────────────────────────────────────────────────

OUT_PATH = ROOT / "data" / "auto_levels_analysis.xlsx"
existing = {}
with pd.ExcelFile(OUT_PATH, engine='openpyxl') as xf:
    for sn in xf.sheet_names:
        existing[sn] = pd.read_excel(xf, sheet_name=sn)

from openpyxl.utils import get_column_letter

def _autofit(sheet):
    for col in sheet.columns:
        max_len = max((len(str(c.value)) for c in col if c.value is not None), default=10)
        sheet.column_dimensions[get_column_letter(col[0].column)].width = min(max_len + 2, 50)

with pd.ExcelWriter(OUT_PATH, engine='openpyxl') as writer:
    for sn, df_ in existing.items():
        df_.to_excel(writer, sheet_name=sn, index=False)
    df_res.drop(columns='sup_maj_err').to_excel(writer, sheet_name='P5 maj_touches x fwd_bars', index=False)
    df_density.to_excel(writer, sheet_name='P5 Density Diagnostic', index=False)
    for sheet in writer.sheets.values():
        _autofit(sheet)

print(f"\nWritten: {OUT_PATH}")
print(f"  Sheets: 'P5 maj_touches x fwd_bars' ({len(df_res)} rows)  |  "
      f"'P5 Density Diagnostic' ({len(df_density)} rows)")
