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
  - Phase 6e ML scoring: XGBoost model scores each accepted level 0–1.
    major = score >= 0.5 (solid line), minor = score < 0.5 (dashed line).
    Falls back to bounce/touches heuristic if model not available.
"""
import numpy as np
import pandas as pd
from pathlib import Path

from data_manager import _get_cache

ROOT = Path(__file__).parent.parent

# ── ML model (lazy-loaded once) ───────────────────────────────────────────────

_ML_MODEL   = None   # XGBClassifier or False (unavailable)
_MODEL_PATH = ROOT / 'data' / 'phase6e_model.json'

_ML_FEATURE_COLS = [
    'pivot_type', 'is_support',
    'bounce', 'touches', 'local_density', 'prominence',
    'vol_zscore', 'consolidation', 'clean_departure',
    'sr_flip', 'price_crossings',
    'dist_from_4pm', 'dist_d5', 'dist_d25', 'dist_d50', 'dist_d100',
    'is_mult5', 'dist_round_to_mult5',
    'days_since_pivot', 'recency_rank',
]

def _load_ml_model():
    global _ML_MODEL
    if _ML_MODEL is None:
        if _MODEL_PATH.exists():
            try:
                import xgboost as xgb
                m = xgb.XGBClassifier()
                m.load_model(str(_MODEL_PATH))
                _ML_MODEL = m
                print(f"ML model loaded: {_MODEL_PATH.name}")
            except Exception as e:
                print(f"WARNING: could not load ML model: {e}")
                _ML_MODEL = False
        else:
            print(f"WARNING: ML model not found at {_MODEL_PATH} — using heuristic major/minor")
            _ML_MODEL = False
    return _ML_MODEL if _ML_MODEL is not False else None


# ── Feature helpers (duplicated from feature_builder to avoid circular import) ─

def _prominence_score(highs, lows, idx, ptype, n):
    lo = max(0, idx - n)
    hi = min(len(highs), idx + n + 1)
    if ptype == 'high':
        neighbours = np.concatenate([highs[lo:idx], highs[idx + 1:hi]])
        return float(highs[idx] - neighbours.max()) if len(neighbours) else 0.0
    else:
        neighbours = np.concatenate([lows[lo:idx], lows[idx + 1:hi]])
        return float(neighbours.min() - lows[idx]) if len(neighbours) else 0.0

def _consolidation_score(highs, lows, idx, price, zone=3.0, lookback=50):
    count = 0
    for k in range(1, min(idx, lookback) + 1):
        i = idx - k
        if lows[i] <= price + zone and highs[i] >= price - zone:
            count += 1
        else:
            break
    return count

def _clean_departure_score(highs_all, lows_all, idx, price, ptype, n_bars):
    end = min(idx + n_bars + 1, len(highs_all))
    fwd_h = highs_all[idx + 1:end]
    fwd_l = lows_all[idx + 1:end]
    if len(fwd_l) == 0:
        return 0.0
    if ptype == 'high':
        return float(price - fwd_l.min())
    else:
        return float(fwd_h.max() - price)

def _sr_flip_score(closes, idx, price, ptype, ph_p, pl_p, zone=2.0):
    segment_c = closes[:idx]
    if ptype == 'high':
        sr_flip = int(len(pl_p) > 0 and np.any(np.abs(pl_p - price) <= zone))
    else:
        sr_flip = int(len(ph_p) > 0 and np.any(np.abs(ph_p - price) <= zone))
    crossings = 0
    if len(segment_c) > 1:
        above = segment_c > price
        crossings = int(np.sum(np.diff(above.astype(int)) != 0))
    return sr_flip, crossings

def _round_distances(price):
    d5   = price % 5;   d5   = min(d5, 5   - d5)
    d25  = price % 25;  d25  = min(d25, 25  - d25)
    d50  = price % 50;  d50  = min(d50, 50  - d50)
    d100 = price % 100; d100 = min(d100, 100 - d100)
    return d5, d25, d50, d100


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
        cutoff = pd.Timestamp(target_date, tz='America/New_York')
        mask  &= idx < cutoff
    candidates = df15_et[mask]
    if candidates.empty:
        return None, None
    bar = candidates.iloc[-1]
    return float(bar['close']), bar.name


def _find_pivots(highs: np.ndarray, lows: np.ndarray, n: int):
    """Vectorised pivot detection."""
    size = len(highs)
    if size < 2 * n + 1:
        empty = np.array([], dtype=np.intp)
        return empty, np.array([]), empty, np.array([])

    center_h = highs[n:size - n]
    center_l = lows[n:size - n]
    ph_ok = np.ones(size - 2 * n, dtype=bool)
    pl_ok = np.ones(size - 2 * n, dtype=bool)

    for k in range(1, n + 1):
        ph_ok &= center_h > highs[n - k:size - n - k]
        pl_ok &= center_l < lows [n - k:size - n - k]
        ph_ok &= center_h > highs[n + k:size - n + k]
        pl_ok &= center_l < lows [n + k:size - n + k]

    centers = np.arange(n, size - n, dtype=np.intp)
    ph_idx  = centers[ph_ok]
    pl_idx  = centers[pl_ok]
    return ph_idx, highs[ph_idx], pl_idx, lows[pl_idx]


# ── main entry point ──────────────────────────────────────────────────────────

def compute_auto_levels(
    pivot_len:        int   = 5,
    price_range:      float = 325.0,
    min_spacing:      float = 3.0,
    touch_zone:       float = 2.0,
    maj_bounce:       float = 40.0,
    maj_touches:      int   = 12,
    forward_bars:     int   = 10,
    min_bounce:       float = 0.0,
    min_score:        float = 0.0,
    show_major_only:  bool  = False,
    show_supports:    bool  = True,
    show_resistances: bool  = True,
    target_date:      str | None = None,
) -> dict:
    """Compute Mancini-style support/resistance levels anchored to most recent 4 PM ET close.

    Each returned level includes a 'score' field (0–1) from the Phase 6e ML model.
    'major' is set to True if score >= 0.5 (solid line) or False otherwise (dashed).
    Falls back to the bounce/touches heuristic if the model file is not available.
    """
    df = _get_cache()
    df15 = _resample_15m(df)

    close4pm, bar4pm_et = _find_4pm_bar(df15, target_date)
    if close4pm is None:
        raise RuntimeError("No 4 PM ET bar found in the cached data.")

    anchor_date = bar4pm_et.strftime('%Y-%m-%d')

    df15_hist = df15[df15.index <= bar4pm_et]
    if df15_hist.empty:
        return {'date': anchor_date, 'close4pm': round(close4pm, 2),
                'supports': [], 'resistances': []}

    highs_hist  = df15_hist['high'].values
    lows_hist   = df15_hist['low'].values
    closes_hist = df15_hist['close'].values
    vols_hist   = df15_hist['volume'].values
    n_hist      = len(df15_hist)
    ts_hist     = df15_hist.index

    highs_all = df15['high'].values
    lows_all  = df15['low'].values
    vols_all  = df15['volume'].values

    ph_idx, ph_p, pl_idx, pl_p = _find_pivots(highs_hist, lows_hist, pivot_len)

    # Build candidate list newest-first.
    candidates = []
    for i in range(len(ph_idx) - 1, -1, -1):
        p = float(ph_p[i])
        if abs(p - close4pm) <= price_range:
            candidates.append({'price': p, 'idx': int(ph_idx[i]), 'type': 'high'})
    for i in range(len(pl_idx) - 1, -1, -1):
        p = float(pl_p[i])
        if abs(p - close4pm) <= price_range:
            candidates.append({'price': p, 'idx': int(pl_idx[i]), 'type': 'low'})
    candidates.sort(key=lambda c: c['idx'], reverse=True)

    touch_ph_p = ph_p
    touch_pl_p = pl_p
    day_vol_mean = float(vols_hist.mean()) or 1.0

    accepted: list[dict] = []

    for cand in candidates:
        p     = cand['price']
        fidx  = cand['idx']
        ptype = cand['type']

        if any(abs(a['price'] - p) < min_spacing for a in accepted):
            continue

        is_res = p > close4pm
        if is_res and not show_resistances:
            continue
        if not is_res and not show_supports:
            continue

        end   = min(fidx + forward_bars + 1, len(highs_all))
        fwd_h = highs_all[fidx + 1:end]
        fwd_l = lows_all [fidx + 1:end]

        if ptype == 'high':
            bounce = float(p - fwd_l.min()) if len(fwd_l) > 0 else 0.0
        else:
            bounce = float(fwd_h.max() - p) if len(fwd_h) > 0 else 0.0

        if bounce < min_bounce:
            continue

        touches = (
            int(np.sum(np.abs(touch_ph_p - p) <= touch_zone)) +
            int(np.sum(np.abs(touch_pl_p - p) <= touch_zone))
        )

        p_rounded = round(p)

        # Store internal fields needed for ML scoring (_prefixed, stripped before return)
        accepted.append({
            'price':    p_rounded,
            'price_lo': p_rounded,
            'price_hi': p_rounded,
            'label':    str(p_rounded),
            'is_res':   is_res,
            # heuristic major (fallback if ML unavailable)
            '_major_heuristic': bounce >= maj_bounce or touches >= maj_touches,
            # for ML feature computation
            '_fidx':    fidx,
            '_ptype':   ptype,
            '_price':   p,         # raw (un-rounded) pivot price
            '_bounce':  bounce,
            '_touches': touches,
        })

    # ── ML scoring ────────────────────────────────────────────────────────────
    model = _load_ml_model()

    if model is not None and accepted:
        accepted_prices_r = np.array([a['price'] for a in accepted], dtype=float)

        rows = []
        for a in accepted:
            fidx   = a['_fidx']
            p      = a['_price']
            p_r    = a['price']
            ptype  = a['_ptype']
            bounce = a['_bounce']
            touches= a['_touches']
            is_res = a['is_res']

            # local_density: other accepted levels within ±10pts
            density = int(np.sum(np.abs(accepted_prices_r - p_r) <= 10.0)) - 1

            # volume z-score
            vol_raw    = float(vols_all[fidx])
            vol_zscore = (vol_raw - day_vol_mean) / (day_vol_mean + 1e-9)

            # prominence, consolidation, clean_departure
            prom   = _prominence_score(highs_hist, lows_hist, fidx, ptype, pivot_len)
            consol = _consolidation_score(highs_hist, lows_hist, fidx, p)
            depart = _clean_departure_score(highs_all, lows_all, fidx, p, ptype, forward_bars)

            # sr_flip + price_crossings
            sr_flip, crossings = _sr_flip_score(closes_hist, fidx, p, ptype, ph_p, pl_p)

            # round-number distances
            d5, d25, d50, d100 = _round_distances(p)
            is_mult5 = int(p_r % 5 == 0)
            r_mod5   = p_r % 5
            dist_round_to_mult5 = min(r_mod5, 5 - r_mod5)

            # days since pivot
            pivot_et   = ts_hist[fidx]
            delta_days = (bar4pm_et.date() - pivot_et.date()).days
            days_since = int(round(delta_days * 252 / 365))

            rows.append([
                int(ptype == 'high'),       # pivot_type
                int(not is_res),            # is_support
                round(bounce, 2),
                touches,
                density,
                round(prom, 2),
                round(vol_zscore, 3),
                consol,
                round(depart, 2),
                sr_flip,
                crossings,
                round(abs(p - close4pm), 2),# dist_from_4pm
                round(d5, 2),
                round(d25, 2),
                round(d50, 2),
                round(d100, 2),
                is_mult5,
                dist_round_to_mult5,
                days_since,
                n_hist - 1 - fidx,          # recency_rank
            ])

        import numpy as _np
        X = _np.array(rows, dtype=_np.float32)
        scores = model.predict_proba(X)[:, 1]

        for a, score in zip(accepted, scores):
            a['score'] = round(float(score), 3)
            a['major'] = bool(score >= 0.5)

    else:
        # Fallback: no model
        for a in accepted:
            a['score'] = None
            a['major'] = a['_major_heuristic']

    # Filter show_major_only after scoring (respects ML major)
    if show_major_only:
        accepted = [a for a in accepted if a['major']]

    # Filter by min_score (only when model is available and min_score > 0)
    if min_score > 0.0 and model is not None:
        accepted = [a for a in accepted if (a.get('score') or 0.0) >= min_score]

    def _clean(lst):
        return [
            {'price':    l['price'],
             'price_lo': l['price_lo'],
             'price_hi': l['price_hi'],
             'major':    l['major'],
             'score':    l.get('score'),
             'label':    l['label']}
            for l in lst
        ]

    def _to_raw(lst):
        return ', '.join(l['label'] + (' (major)' if l['major'] else '') for l in lst)

    supports    = _clean([l for l in accepted if not l['is_res']])
    resistances = _clean([l for l in accepted if     l['is_res']])

    supports_sorted    = sorted(supports,    key=lambda l: l['price'], reverse=True)
    resistances_sorted = sorted(resistances, key=lambda l: l['price'])

    ml_str = f"  ML scored" if model is not None else "  (no ML model)"
    print(f"Auto levels: anchor={anchor_date}  close4pm={close4pm:.2f}  "
          f"sup={len(supports)}  res={len(resistances)}{ml_str}")

    return {
        'date':            anchor_date,
        'close4pm':        round(close4pm, 2),
        'supports':        supports,
        'resistances':     resistances,
        'supports_raw':    _to_raw(supports_sorted),
        'resistances_raw': _to_raw(resistances_sorted),
    }
