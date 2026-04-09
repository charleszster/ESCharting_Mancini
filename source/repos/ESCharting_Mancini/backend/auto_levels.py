"""
Auto level generation — Mancini-style, 15-min bars.
Anchored to the most recent 4:00 PM ET closing bar.

Methodology:
  - Aggregate 1-min cache to 15-min bars (ET-aligned)
  - Find the most recent bar whose close = 4:00 PM ET (labeled 15:45 ET on 15-min chart)
  - Detect pivot highs/lows using N bars on each side (vectorised)
  - Filter to pivots within ±price_range of close4pm, at or before 4pm bar
  - Process newest-first so most recent test of a price zone wins dedup
  - Bounce follows pivot type (not classification):
      pivot high → bounce = high − min_low in forward window
      pivot low  → bounce = max_high − low in forward window
  - Classification is by price vs close4pm (above = resistance, below = support)
  - Major if bounce >= maj_bounce OR touches >= maj_touches
"""
import numpy as np
import pandas as pd

from data_manager import _get_cache


# ── helpers ───────────────────────────────────────────────────────────────────

def _resample_15m(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate 1-min front-month cache to 15-min bars, ET-indexed."""
    df_et = df[['open', 'high', 'low', 'close', 'volume']].copy()
    df_et.index = df_et.index.tz_convert('America/New_York')
    return (
        df_et.resample('15min')
        .agg(
            open=('open',   'first'),
            high=('high',   'max'),
            low =('low',    'min'),
            close=('close', 'last'),
            volume=('volume', 'sum'),
        )
        .dropna(subset=['open'])
    )


def _find_4pm_bar(df15_et: pd.DataFrame, target_date: str | None = None):
    """Return (close_price, bar_et_timestamp) of the most recent 4 PM ET bar.

    On a 15-min ET chart the bar *labeled* 15:45 closes at 16:00 ET.
    If target_date (YYYY-MM-DD) is given, finds the most recent 4pm bar
    on or before that date; otherwise uses the most recent bar in the data.
    """
    idx = df15_et.index
    mask = (idx.hour == 15) & (idx.minute == 45) & (idx.weekday < 5)
    if target_date:
        # target_date is the day levels are FOR; anchor is the prior trading day's 4pm bar.
        # Use strict less-than so a Monday picks Friday's 4pm, not Monday's.
        cutoff = pd.Timestamp(target_date, tz='America/New_York')
        mask  &= idx < cutoff
    candidates = df15_et[mask]
    if candidates.empty:
        return None, None
    bar = candidates.iloc[-1]
    return float(bar['close']), bar.name  # bar.name = ET Timestamp


def _find_pivots(highs: np.ndarray, lows: np.ndarray, n: int):
    """Vectorised pivot detection.

    A pivot high at index i requires highs[i] > highs[i±k] for all k in [1..n].
    Same logic inverted for pivot lows.

    Returns (ph_idx, ph_prices, pl_idx, pl_prices) — indices into the input arrays.
    """
    size = len(highs)
    if size < 2 * n + 1:
        empty = np.array([], dtype=np.intp)
        return empty, np.array([]), empty, np.array([])

    center_h = highs[n:size - n]
    center_l = lows[n:size - n]
    ph_ok = np.ones(size - 2 * n, dtype=bool)
    pl_ok = np.ones(size - 2 * n, dtype=bool)

    for k in range(1, n + 1):
        # left neighbours at offset k
        ph_ok &= center_h > highs[n - k:size - n - k]
        pl_ok &= center_l < lows [n - k:size - n - k]
        # right neighbours at offset k
        ph_ok &= center_h > highs[n + k:size - n + k]
        pl_ok &= center_l < lows [n + k:size - n + k]

    centers = np.arange(n, size - n, dtype=np.intp)
    ph_idx  = centers[ph_ok]
    pl_idx  = centers[pl_ok]
    return ph_idx, highs[ph_idx], pl_idx, lows[pl_idx]


# ── main entry point ──────────────────────────────────────────────────────────

def compute_auto_levels(
    pivot_len:        int   = 5,
    price_range:      float = 250.0,
    min_spacing:      float = 3.0,
    touch_zone:       float = 2.0,
    maj_bounce:       float = 40.0,
    maj_touches:      int   = 5,
    forward_bars:     int   = 100,
    show_major_only:  bool  = False,
    show_supports:    bool  = True,
    show_resistances: bool  = True,
    target_date:      str | None = None,
) -> dict:
    """Compute Mancini-style support/resistance levels anchored to most recent 4 PM ET close.

    If target_date (YYYY-MM-DD) is provided, anchors to the most recent 4pm bar
    on or before that date instead of the absolute most recent.
    """
    df = _get_cache()   # DatetimeIndex UTC, columns: open high low close volume adj_offset

    df15 = _resample_15m(df)   # ET-indexed 15-min bars

    close4pm, bar4pm_et = _find_4pm_bar(df15, target_date)
    if close4pm is None:
        raise RuntimeError("No 4 PM ET bar found in the cached data.")

    anchor_date = bar4pm_et.strftime('%Y-%m-%d')

    # Historical slice: all bars up to and including the 4pm anchor bar.
    # Because df15 is sorted ascending and df15_hist is a prefix of df15,
    # numpy index i in df15_hist corresponds to the same index i in df15.
    df15_hist = df15[df15.index <= bar4pm_et]
    if df15_hist.empty:
        return {'date': anchor_date, 'close4pm': round(close4pm, 2),
                'supports': [], 'resistances': []}

    highs_hist = df15_hist['high'].values
    lows_hist  = df15_hist['low'].values
    highs_all  = df15['high'].values   # full range — forward window may extend past 4pm
    lows_all   = df15['low'].values

    ph_idx, ph_p, pl_idx, pl_p = _find_pivots(highs_hist, lows_hist, pivot_len)

    # Build candidate list, newest-first within each pivot type, then interleaved by index.
    candidates = []
    for i in range(len(ph_idx) - 1, -1, -1):
        p = float(ph_p[i])
        if abs(p - close4pm) <= price_range:
            candidates.append({'price': p, 'idx': int(ph_idx[i]), 'type': 'high'})
    for i in range(len(pl_idx) - 1, -1, -1):
        p = float(pl_p[i])
        if abs(p - close4pm) <= price_range:
            candidates.append({'price': p, 'idx': int(pl_idx[i]), 'type': 'low'})

    # Sort all candidates newest-first so the most recent test of any price zone wins.
    candidates.sort(key=lambda c: c['idx'], reverse=True)

    # Touch arrays — only hist-range pivots (at or before 4pm), all prices.
    touch_ph_p = ph_p
    touch_pl_p = pl_p

    accepted: list[dict] = []

    for cand in candidates:
        p     = cand['price']
        fidx  = cand['idx']
        ptype = cand['type']

        # Deduplication: skip if within min_spacing of any already-accepted level.
        if any(abs(a['price'] - p) < min_spacing for a in accepted):
            continue

        # Classify by price location relative to close4pm.
        is_res = p > close4pm
        if is_res and not show_resistances:
            continue
        if not is_res and not show_supports:
            continue

        # Bounce — follows pivot type, not classification.
        end    = min(fidx + forward_bars + 1, len(highs_all))
        fwd_h  = highs_all[fidx + 1:end]
        fwd_l  = lows_all [fidx + 1:end]

        if ptype == 'high':
            bounce = float(p - fwd_l.min()) if len(fwd_l) > 0 else 0.0
        else:
            bounce = float(fwd_h.max() - p) if len(fwd_h) > 0 else 0.0

        # Touch count — pivots within ±touch_zone of this price, at or before 4pm.
        touches = (
            int(np.sum(np.abs(touch_ph_p - p) <= touch_zone)) +
            int(np.sum(np.abs(touch_pl_p - p) <= touch_zone))
        )

        is_major = bounce >= maj_bounce or touches >= maj_touches
        if show_major_only and not is_major:
            continue

        label = f"{p:.2f}".rstrip('0').rstrip('.')

        accepted.append({
            'price':    round(p, 2),
            'price_lo': round(p, 2),
            'price_hi': round(p, 2),
            'major':    is_major,
            'label':    label,
            'is_res':   is_res,
        })

    def _clean(lst: list[dict]) -> list[dict]:
        return [
            {'price': l['price'], 'price_lo': l['price_lo'], 'price_hi': l['price_hi'],
             'major': l['major'],  'label': l['label']}
            for l in lst
        ]

    def _to_raw(lst: list[dict]) -> str:
        parts = []
        for l in lst:
            parts.append(l['label'] + (' (major)' if l['major'] else ''))
        return ', '.join(parts)

    supports    = _clean([l for l in accepted if not l['is_res']])
    resistances = _clean([l for l in accepted if     l['is_res']])

    # Sort for display: supports descending (nearest first), resistances ascending
    supports_sorted    = sorted(supports,    key=lambda l: l['price'], reverse=True)
    resistances_sorted = sorted(resistances, key=lambda l: l['price'])

    print(f"Auto levels: anchor={anchor_date}  close4pm={close4pm:.2f}  "
          f"sup={len(supports)}  res={len(resistances)}")

    return {
        'date':            anchor_date,
        'close4pm':        round(close4pm, 2),
        'supports':        supports,
        'resistances':     resistances,
        'supports_raw':    _to_raw(supports_sorted),
        'resistances_raw': _to_raw(resistances_sorted),
    }
