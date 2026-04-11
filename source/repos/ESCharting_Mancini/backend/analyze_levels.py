"""
Auto level analysis: compare our generated levels vs Mancini's stored levels.
Run from the backend directory: python analyze_levels.py
"""
import sys, re, sqlite3
import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path(__file__).parent.parent

from data_manager import warm_cache
from auto_levels import compute_auto_levels

# ── parameters (defaults used by the app) ─────────────────────────────────────
PARAMS = dict(
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
MATCH_TOL = 2.0
DATE_FROM = "2025-12-10"

# ── warm cache once ────────────────────────────────────────────────────────────
print("Warming cache ...")
warm_cache()
print("Cache ready.")

# ── Mancini level parser ───────────────────────────────────────────────────────
def _parse_price_token(tok: str) -> float:
    tok = tok.strip().strip(',')
    m = re.match(r'^(\d+)-(\d+)$', tok)
    if m:
        a, b_raw = m.group(1), m.group(2)
        b = (a[:len(a) - len(b_raw)] + b_raw) if len(b_raw) < len(a) else b_raw
        return (float(a) + float(b)) / 2
    return float(tok)

def parse_mancini_levels(text: str) -> list:
    if not text:
        return []
    clean = re.sub(r'\s*\(major\)', '', text)
    prices = []
    for part in clean.split(','):
        part = part.strip()
        if not part:
            continue
        try:
            prices.append(_parse_price_token(part))
        except Exception:
            pass
    return sorted(prices)

# ── load Mancini dates ─────────────────────────────────────────────────────────
DB_PATH = ROOT / "data" / "levels.db"
conn = sqlite3.connect(DB_PATH)
rows = conn.execute(
    "SELECT trading_date, supports, resistances FROM levels "
    "WHERE trading_date >= ? ORDER BY trading_date",
    (DATE_FROM,)
).fetchall()
conn.close()
print(f"Mancini rows in window: {len(rows)}")

# ── generate our levels for each date ─────────────────────────────────────────
records = []
for i, (trade_date, m_sup_raw, m_res_raw) in enumerate(rows):
    print(f"  [{i+1}/{len(rows)}] {trade_date}", end='\r', flush=True)
    try:
        result = compute_auto_levels(target_date=trade_date, **PARAMS)
    except Exception as e:
        print(f"\n  ERROR on {trade_date}: {e}")
        continue
    records.append({
        'trade_date': trade_date,
        'our_sup':    sorted([l['price'] for l in result['supports']], reverse=True),
        'our_res':    sorted([l['price'] for l in result['resistances']]),
        'm_sup':      sorted(parse_mancini_levels(m_sup_raw), reverse=True),
        'm_res':      sorted(parse_mancini_levels(m_res_raw)),
    })
print(f"\nGenerated {len(records)} records.")

# ── matching helper ────────────────────────────────────────────────────────────
def count_matches(a_list, b_list, tol=MATCH_TOL):
    if not a_list or not b_list:
        return 0
    b_arr = np.array(b_list)
    return sum(1 for p in a_list if np.min(np.abs(b_arr - p)) <= tol)

def fmt_levels(lst):
    return ', '.join(f"{p:.2f}".rstrip('0').rstrip('.') for p in lst)

# ── Sheet 1: Levels by Date ────────────────────────────────────────────────────
sheet1_rows = []
for r in records:
    sheet1_rows.append({
        'Trade Date':          r['trade_date'],
        'Our Supports':        fmt_levels(r['our_sup']),
        'Our Resistances':     fmt_levels(r['our_res']),
        'Mancini Supports':    fmt_levels(r['m_sup']),
        'Mancini Resistances': fmt_levels(r['m_res']),
    })
df1 = pd.DataFrame(sheet1_rows)

# ── Sheet 2: Parameters ────────────────────────────────────────────────────────
df2 = pd.DataFrame([
    {'Parameter': 'Pivot lookback (bars/side)',  'Value': PARAMS['pivot_len'],        'Notes': 'integer'},
    {'Parameter': 'Price range (±pts)',           'Value': PARAMS['price_range'],      'Notes': 'float'},
    {'Parameter': 'Min level spacing (pts)',      'Value': PARAMS['min_spacing'],      'Notes': 'float'},
    {'Parameter': 'Touch zone (±pts)',            'Value': PARAMS['touch_zone'],       'Notes': 'float'},
    {'Parameter': 'Major bounce threshold (pts)', 'Value': PARAMS['maj_bounce'],       'Notes': 'float'},
    {'Parameter': 'Major touch threshold',        'Value': PARAMS['maj_touches'],      'Notes': 'integer'},
    {'Parameter': 'Bounce forward window (bars)', 'Value': PARAMS['forward_bars'],     'Notes': 'integer (1 bar = 15 min)'},
    {'Parameter': 'Show major only',              'Value': PARAMS['show_major_only'],  'Notes': 'bool'},
    {'Parameter': 'Show supports',                'Value': PARAMS['show_supports'],    'Notes': 'bool'},
    {'Parameter': 'Show resistances',             'Value': PARAMS['show_resistances'], 'Notes': 'bool'},
    {'Parameter': 'Match tolerance (±pts)',        'Value': MATCH_TOL,                  'Notes': 'used in statistics only'},
    {'Parameter': 'Analysis date range',          'Value': f"{DATE_FROM} to 2026-04-10", 'Notes': ''},
    {'Parameter': 'Trading days analyzed',        'Value': len(records),               'Notes': ''},
])

# ── Per-day stats ──────────────────────────────────────────────────────────────
stat_rows = []
for r in records:
    os_, or_ = r['our_sup'],  r['our_res']
    ms_, mr_ = r['m_sup'],    r['m_res']
    n_os, n_ms = len(os_), len(ms_)
    n_or, n_mr = len(or_), len(mr_)
    sup_om = count_matches(os_, ms_)
    sup_mm = count_matches(ms_, os_)
    res_om = count_matches(or_, mr_)
    res_mm = count_matches(mr_, or_)
    stat_rows.append({
        'Trade Date':            r['trade_date'],
        '# Our Sup':             n_os,
        '# Mancini Sup':         n_ms,
        '# Our Sup Matched':     sup_om,
        '# Mancini Sup Matched': sup_mm,
        'Our Sup Precision %':   round(sup_om/n_os*100, 1) if n_os else None,
        'Mancini Sup Recall %':  round(sup_mm/n_ms*100, 1) if n_ms else None,
        '# Our Res':             n_or,
        '# Mancini Res':         n_mr,
        '# Our Res Matched':     res_om,
        '# Mancini Res Matched': res_mm,
        'Our Res Precision %':   round(res_om/n_or*100, 1) if n_or else None,
        'Mancini Res Recall %':  round(res_mm/n_mr*100, 1) if n_mr else None,
    })
df_stat = pd.DataFrame(stat_rows)

def safe_mean(s):
    s = s.dropna()
    return round(s.mean(), 1) if len(s) else 'N/A'

tot_os  = df_stat['# Our Sup'].sum()
tot_ms  = df_stat['# Mancini Sup'].sum()
tot_or  = df_stat['# Our Res'].sum()
tot_mr  = df_stat['# Mancini Res'].sum()
tot_os_hit = df_stat['# Our Sup Matched'].sum()
tot_ms_hit = df_stat['# Mancini Sup Matched'].sum()
tot_or_hit = df_stat['# Our Res Matched'].sum()
tot_mr_hit = df_stat['# Mancini Res Matched'].sum()

summary_rows = [
    ('Trading days in analysis',  len(records), len(records), len(records)),
    ('Match tolerance (±pts)',     MATCH_TOL, MATCH_TOL, MATCH_TOL),
    ('', '', '', ''),
    ('=== Level Counts ===', '', '', ''),
    ('Avg levels/day (ours)',      safe_mean(df_stat['# Our Sup']),     safe_mean(df_stat['# Our Res']),     round((tot_os+tot_or)/len(records), 1)),
    ('Avg levels/day (Mancini)',   safe_mean(df_stat['# Mancini Sup']), safe_mean(df_stat['# Mancini Res']), round((tot_ms+tot_mr)/len(records), 1)),
    ('Total levels (ours)',        int(tot_os), int(tot_or), int(tot_os+tot_or)),
    ('Total levels (Mancini)',     int(tot_ms), int(tot_mr), int(tot_ms+tot_mr)),
    ('', '', '', ''),
    ('=== Precision: % of OUR levels that match Mancini ===', '', '', ''),
    ('Our levels matched',         int(tot_os_hit), int(tot_or_hit), int(tot_os_hit+tot_or_hit)),
    ('Precision % (pooled)',
        f"{tot_os_hit/tot_os*100:.1f}%" if tot_os else 'N/A',
        f"{tot_or_hit/tot_or*100:.1f}%" if tot_or else 'N/A',
        f"{(tot_os_hit+tot_or_hit)/(tot_os+tot_or)*100:.1f}%" if (tot_os+tot_or) else 'N/A'),
    ('Avg daily precision %',      safe_mean(df_stat['Our Sup Precision %']),  safe_mean(df_stat['Our Res Precision %']),  ''),
    ('', '', '', ''),
    ('=== Recall: % of MANCINI levels we captured ===', '', '', ''),
    ('Mancini levels we matched',  int(tot_ms_hit), int(tot_mr_hit), int(tot_ms_hit+tot_mr_hit)),
    ('Recall % (pooled)',
        f"{tot_ms_hit/tot_ms*100:.1f}%" if tot_ms else 'N/A',
        f"{tot_mr_hit/tot_mr*100:.1f}%" if tot_mr else 'N/A',
        f"{(tot_ms_hit+tot_mr_hit)/(tot_ms+tot_mr)*100:.1f}%" if (tot_ms+tot_mr) else 'N/A'),
    ('Avg daily recall %',         safe_mean(df_stat['Mancini Sup Recall %']), safe_mean(df_stat['Mancini Res Recall %']), ''),
]

df3 = pd.DataFrame(summary_rows, columns=['Metric', 'Supports', 'Resistances', 'Combined'])

# ── write Excel ────────────────────────────────────────────────────────────────
OUT_PATH = ROOT / "data" / "auto_levels_analysis.xlsx"

with pd.ExcelWriter(OUT_PATH, engine='openpyxl') as writer:
    df1.to_excel(writer, sheet_name='Levels by Date', index=False)
    df2.to_excel(writer, sheet_name='Parameters', index=False)
    df3.to_excel(writer, sheet_name='Statistics', index=False)
    df_stat.to_excel(writer, sheet_name='Daily Detail', index=False)

    from openpyxl.utils import get_column_letter
    for sheet in writer.sheets.values():
        for col in sheet.columns:
            max_len = max((len(str(c.value)) for c in col if c.value is not None), default=10)
            sheet.column_dimensions[get_column_letter(col[0].column)].width = min(max_len + 2, 100)

print(f"Written: {OUT_PATH}")
