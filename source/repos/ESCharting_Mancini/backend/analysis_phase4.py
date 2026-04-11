"""
Phase 4: forward_bars sweep in short range (2–16 bars = 30min–4hr)
Goal: find forward_bars value where our major% matches Mancini's ~42%
Base: price_range=325, min_spacing=3.0, min_bounce=20
"""
import re, sqlite3
import pandas as pd
import numpy as np
from pathlib import Path
from copy import deepcopy

ROOT = Path(__file__).parent.parent

from data_manager import warm_cache, _get_cache
from auto_levels import compute_auto_levels, _resample_15m, _find_4pm_bar

MATCH_TOL = 2.0
DATE_FROM  = "2025-12-10"

BASE = dict(
    pivot_len=5, price_range=325.0, min_spacing=3.0, touch_zone=2.0,
    maj_bounce=40.0, maj_touches=5, forward_bars=100, min_bounce=20.0,
    show_major_only=False, show_supports=True, show_resistances=True,
)

print("Warming cache ...")
warm_cache()
print("Cache ready.")

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

conn = sqlite3.connect(ROOT / "data" / "levels.db")
rows = conn.execute(
    "SELECT trading_date, supports, resistances FROM levels "
    "WHERE trading_date >= ? ORDER BY trading_date", (DATE_FROM,)
).fetchall()
conn.close()

df_cache = _get_cache()
df15 = _resample_15m(df_cache)

mancini = {}
close4pm_map = {}
for td, ms, mr in rows:
    mancini[td] = {
        'sup': parse_mancini(ms), 'res': parse_mancini(mr),
        'sup_maj': parse_mancini_with_major(ms),
        'res_maj': parse_mancini_with_major(mr),
    }
    c4, _ = _find_4pm_bar(df15, td)
    close4pm_map[td] = c4

dates = list(mancini.keys())

man_sup_total = sum(len(mancini[d]['sup']) for d in dates)
man_res_total = sum(len(mancini[d]['res']) for d in dates)
man_sup_major = sum(sum(1 for _,m in mancini[d]['sup_maj'] if m) for d in dates)
man_res_major = sum(sum(1 for _,m in mancini[d]['res_maj'] if m) for d in dates)
print(f"Mancini major %: sup={man_sup_major/man_sup_total*100:.1f}%  res={man_res_major/man_res_total*100:.1f}%")
print(f"Target: ~42% major")

results = []
SWEEP = [2, 3, 4, 5, 6, 7, 8, 10, 12, 16, 100]

for i, fb in enumerate(SWEEP):
    print(f"  [{i+1}/{len(SWEEP)}] forward_bars={fb} ({fb*15}min)", end='\r', flush=True)
    p = deepcopy(BASE); p['forward_bars'] = fb
    rows_out = []
    for td in dates:
        try:
            r = compute_auto_levels(target_date=td, **p)
        except: continue
        sups = r['supports']; ress = r['resistances']
        os_ = [l['price'] for l in sups]; or_ = [l['price'] for l in ress]
        ms_ = mancini[td]['sup'];          mr_ = mancini[td]['res']
        rows_out.append({
            'n_our_sup': len(os_), 'n_man_sup': len(ms_),
            'n_our_res': len(or_), 'n_man_res': len(mr_),
            'sup_prec': count_matches(os_,ms_)/len(os_)*100 if os_ else None,
            'sup_rec':  count_matches(ms_,os_)/len(ms_)*100 if ms_ else None,
            'res_prec': count_matches(or_,mr_)/len(or_)*100 if or_ else None,
            'res_rec':  count_matches(mr_,or_)/len(mr_)*100 if mr_ else None,
            'our_sup_major': sum(1 for l in sups if l.get('major')),
            'our_res_major': sum(1 for l in ress if l.get('major')),
            'our_sup': os_, 'our_res': or_, 'man_sup': ms_, 'man_res': mr_,
        })
    df_r = pd.DataFrame(rows_out)
    tot_os = df_r['n_our_sup'].sum(); tot_or = df_r['n_our_res'].sum()
    hit_ms = sum(count_matches(r.man_sup, r.our_sup) for r in df_r.itertuples())
    hit_mr = sum(count_matches(r.man_res, r.our_res) for r in df_r.itertuples())
    hit_os = sum(count_matches(r.our_sup, r.man_sup) for r in df_r.itertuples())
    hit_or = sum(count_matches(r.our_res, r.man_res) for r in df_r.itertuples())
    tot_ms = df_r['n_man_sup'].sum(); tot_mr = df_r['n_man_res'].sum()
    sup_maj_pct = df_r['our_sup_major'].sum() / tot_os * 100 if tot_os else 0
    res_maj_pct = df_r['our_res_major'].sum() / tot_or * 100 if tot_or else 0
    results.append({
        'forward_bars': fb,
        'window_min':   fb * 15,
        'sup_prec':     round(hit_os/tot_os*100, 1) if tot_os else 0,
        'sup_rec':      round(hit_ms/tot_ms*100, 1) if tot_ms else 0,
        'res_prec':     round(hit_or/tot_or*100, 1) if tot_or else 0,
        'res_rec':      round(hit_mr/tot_mr*100, 1) if tot_mr else 0,
        'avg_our':      round((tot_os+tot_or)/len(df_r), 1),
        'our_sup_maj%': round(sup_maj_pct, 1),
        'our_res_maj%': round(res_maj_pct, 1),
    })

print()
df_res = pd.DataFrame(results)
print(df_res.to_string(index=False))

# Write to Excel
OUT_PATH = ROOT / "data" / "auto_levels_analysis.xlsx"
existing = {}
with pd.ExcelFile(OUT_PATH, engine='openpyxl') as xf:
    for sn in xf.sheet_names:
        existing[sn] = pd.read_excel(xf, sheet_name=sn)

from openpyxl.utils import get_column_letter
with pd.ExcelWriter(OUT_PATH, engine='openpyxl') as writer:
    for sn, df_ in existing.items():
        df_.to_excel(writer, sheet_name=sn, index=False)
    df_res.to_excel(writer, sheet_name='P4 forward_bars Short', index=False)
    for sheet in writer.sheets.values():
        for col in sheet.columns:
            max_len = max((len(str(c.value)) for c in col if c.value is not None), default=10)
            sheet.column_dimensions[get_column_letter(col[0].column)].width = min(max_len+2, 80)

print(f"Written: {OUT_PATH}")
