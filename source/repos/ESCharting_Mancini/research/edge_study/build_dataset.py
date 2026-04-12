"""
build_dataset.py — Phase 1: Build the level-touch events dataset.

For each trading day in the study window:
  1. Compute auto levels anchored to the prior 4pm ET close
  2. Scan that session's 1-min bars for level touch episodes
  3. Extract level features + 5 context feature groups at each touch
  4. Label outcomes (forward price movement, binary win/loss)

Output: research/edge_study/data/touch_events.parquet

Usage:
    python build_dataset.py
    python build_dataset.py --start 2024-01-01 --end 2026-03-25
    python build_dataset.py --start 2025-01-01  # test on recent year first
"""

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

# ── path setup ────────────────────────────────────────────────────────────────
ROOT    = Path(__file__).parent.parent.parent
BACKEND = ROOT / 'backend'
OUT_DIR = Path(__file__).parent / 'data'
OUT_DIR.mkdir(exist_ok=True)
sys.path.insert(0, str(BACKEND))

from data_manager import _get_cache
from auto_levels import (
    _resample_15m, _find_4pm_bar, _find_pivots,
    _ath_cluster_candidates, _load_ml_model,
    _prominence_score, _consolidation_score, _clean_departure_score,
    _sr_flip_score, _round_distances,
)

# ── study parameters ──────────────────────────────────────────────────────────
PIVOT_LEN     = 5
PRICE_RANGE   = 325.0
MIN_SPACING   = 3.0
TOUCH_ZONE    = 2.0
MAJ_BOUNCE    = 40.0
MAJ_TOUCHES   = 12
FORWARD_BARS  = 10
ATH_CLUSTER_N = 15

TOUCH_COOLDOWN   = 15   # min bars gap between separate touch episodes of same level
APPROACH_LOOKBACK= 20   # 1-min bars to measure approach velocity
TREND_SHORT      = 60   # 1-min bars for short-term trend
TREND_LONG       = 240  # 1-min bars for long-term trend (~4hr)
VOL_LOOKBACK     = 20   # 1-min bars for volume z-score baseline

OUTCOME_WINDOWS  = [10, 30, 60, 120]   # 1-min bars forward
TARGET_PTS       = 10.0                 # favorable threshold (binary win)
STOP_PTS         = 5.0                  # adverse threshold (binary stop)
BREAK_LOOKBACK   = 10                   # bars to detect a "break" below support
RECLAIM_WINDOW   = 30                   # bars after break to check for reclaim

RTH_OPEN_MIN  = 9 * 60 + 30   # 570 mins since midnight ET
RTH_CLOSE_MIN = 16 * 60        # 960


# ── helper: get all anchor dates in the data ─────────────────────────────────

def get_anchor_dates(df15_et: pd.DataFrame,
                     start: str | None,
                     end: str | None) -> list[pd.Timestamp]:
    """Return all 4pm ET bar timestamps within [start, end]."""
    idx = df15_et.index
    mask = (idx.hour == 15) & (idx.minute == 45) & (idx.weekday < 5)
    anchors = df15_et[mask].index.tolist()
    if start:
        s = pd.Timestamp(start, tz='America/New_York')
        anchors = [a for a in anchors if a >= s]
    if end:
        e = pd.Timestamp(end, tz='America/New_York')
        anchors = [a for a in anchors if a <= e]
    return anchors


# ── helper: compute levels for one anchor date ────────────────────────────────

def compute_levels_for_anchor(
    df15_et:   pd.DataFrame,
    highs_all: np.ndarray,
    lows_all:  np.ndarray,
    vols_all:  np.ndarray,
    bar4pm_et: pd.Timestamp,
    model,
) -> list[dict]:
    """Compute accepted levels for one anchor, returning full feature dicts."""
    close4pm = float(df15_et.loc[bar4pm_et, 'close'])

    df15_hist  = df15_et[df15_et.index <= bar4pm_et]
    if df15_hist.empty:
        return []

    highs_hist  = df15_hist['high'].values
    lows_hist   = df15_hist['low'].values
    closes_hist = df15_hist['close'].values
    vols_hist   = df15_hist['volume'].values
    n_hist      = len(df15_hist)
    ts_hist     = df15_hist.index

    day_vol_mean = float(vols_hist.mean()) or 1.0

    ph_idx, ph_p, pl_idx, pl_p = _find_pivots(highs_hist, lows_hist, PIVOT_LEN)

    candidates = []
    for i in range(len(ph_idx) - 1, -1, -1):
        p = float(ph_p[i])
        if abs(p - close4pm) <= PRICE_RANGE:
            candidates.append({'price': p, 'idx': int(ph_idx[i]), 'type': 'high'})
    for i in range(len(pl_idx) - 1, -1, -1):
        p = float(pl_p[i])
        if abs(p - close4pm) <= PRICE_RANGE:
            candidates.append({'price': p, 'idx': int(pl_idx[i]), 'type': 'low'})
    candidates.sort(key=lambda c: c['idx'], reverse=True)

    accepted: list[dict] = []

    for cand in candidates:
        p     = cand['price']
        fidx  = cand['idx']
        ptype = cand['type']

        if any(abs(a['_price_raw'] - p) < MIN_SPACING for a in accepted):
            continue

        is_res = p > close4pm

        end   = min(fidx + FORWARD_BARS + 1, len(highs_all))
        fwd_h = highs_all[fidx + 1:end]
        fwd_l = lows_all[fidx + 1:end]

        bounce  = float(p - fwd_l.min()) if ptype == 'high' and len(fwd_l) > 0 else \
                  float(fwd_h.max() - p) if ptype == 'low'  and len(fwd_h) > 0 else 0.0

        touches = (int(np.sum(np.abs(ph_p - p) <= TOUCH_ZONE)) +
                   int(np.sum(np.abs(pl_p - p) <= TOUCH_ZONE)))

        accepted.append({
            'price':       round(p),
            '_price_raw':  p,
            'is_res':      is_res,
            '_fidx':       fidx,
            '_ptype':      ptype,
            '_bounce':     bounce,
            '_touches':    touches,
            '_ath_cluster': False,
        })

    # ATH cluster injection
    ath_cands = _ath_cluster_candidates(
        highs_hist, close4pm, PRICE_RANGE, accepted,
        ath_spacing=5.0, min_spacing=MIN_SPACING, top_n=ATH_CLUSTER_N,
    )
    for ac in ath_cands:
        p    = ac['price']
        fidx = ac['idx']
        p_r  = ac['price_r']
        end   = min(fidx + FORWARD_BARS + 1, len(highs_all))
        fwd_l = lows_all[fidx + 1:end]
        bounce = float(p - fwd_l.min()) if len(fwd_l) > 0 else 0.0
        touches = (int(np.sum(np.abs(ph_p - p) <= TOUCH_ZONE)) +
                   int(np.sum(np.abs(pl_p - p) <= TOUCH_ZONE)))
        accepted.append({
            'price':       p_r,
            '_price_raw':  p,
            'is_res':      True,
            '_fidx':       fidx,
            '_ptype':      'high',
            '_bounce':     bounce,
            '_touches':    touches,
            '_ath_cluster': True,
        })

    if not accepted:
        return []

    accepted_prices_r = np.array([a['price'] for a in accepted], dtype=float)

    # ── ML scoring ────────────────────────────────────────────────────────────
    if model is not None:
        rows = []
        for a in accepted:
            fidx   = a['_fidx']
            p      = a['_price_raw']
            p_r    = a['price']
            ptype  = a['_ptype']
            bounce = a['_bounce']
            touches= a['_touches']
            is_res = a['is_res']

            density    = int(np.sum(np.abs(accepted_prices_r - p_r) <= 10.0)) - 1
            vol_raw    = float(vols_all[fidx])
            vol_zscore = (vol_raw - day_vol_mean) / (day_vol_mean + 1e-9)
            prom       = _prominence_score(highs_hist, lows_hist, fidx, ptype, PIVOT_LEN)
            consol     = _consolidation_score(highs_hist, lows_hist, fidx, p)
            depart     = _clean_departure_score(highs_all, lows_all, fidx, p, ptype, FORWARD_BARS)
            sr_flip, crossings = _sr_flip_score(closes_hist, fidx, p, ptype, ph_p, pl_p)
            d5, d25, d50, d100 = _round_distances(p)
            is_mult5   = int(p_r % 5 == 0)
            r_mod5     = p_r % 5
            dist_r5    = min(r_mod5, 5 - r_mod5)
            pivot_et   = ts_hist[fidx]
            delta_days = (bar4pm_et.date() - pivot_et.date()).days
            days_since = int(round(delta_days * 252 / 365))

            rows.append([
                int(ptype == 'high'), int(not is_res),
                round(bounce, 2), touches, density,
                round(prom, 2), round(vol_zscore, 3), consol,
                round(depart, 2), sr_flip, crossings,
                round(abs(p - close4pm), 2),
                round(d5, 2), round(d25, 2), round(d50, 2), round(d100, 2),
                is_mult5, dist_r5, days_since, n_hist - 1 - fidx,
            ])

            # Store level features for output
            a['ml_score']          = None   # filled after model run
            a['sr_flip']           = sr_flip
            a['price_crossings']   = crossings
            a['dist_from_4pm']     = round(abs(p - close4pm), 2)
            a['historical_touches']= touches
            a['days_since_pivot']  = days_since
            a['recency_rank']      = n_hist - 1 - fidx
            a['local_density']     = density
            a['is_mult5']          = is_mult5
            a['dist_round']        = round(d25, 2)
            a['historical_bounce'] = round(bounce, 2)
            a['close4pm']          = round(close4pm, 2)

        import numpy as _np
        X      = _np.array(rows, dtype=_np.float32)
        scores = model.predict_proba(X)[:, 1]
        for a, score in zip(accepted, scores):
            a['ml_score'] = round(float(score), 3)
            a['is_major'] = bool(score >= 0.5)
    else:
        for a in accepted:
            a['ml_score']           = None
            a['is_major']           = a['_bounce'] >= MAJ_BOUNCE or a['_touches'] >= MAJ_TOUCHES
            a['sr_flip']            = 0
            a['price_crossings']    = 0
            a['dist_from_4pm']      = round(abs(a['_price_raw'] - close4pm), 2)
            a['historical_touches'] = a['_touches']
            a['days_since_pivot']   = 0
            a['recency_rank']       = 0
            a['local_density']      = 0
            a['is_mult5']           = int(a['price'] % 5 == 0)
            a['dist_round']         = 0.0
            a['historical_bounce']  = round(a['_bounce'], 2)
            a['close4pm']           = round(close4pm, 2)

    return accepted


# ── helper: find touch episodes for one level on one session ─────────────────

def find_touch_episodes(
    closes: np.ndarray,
    highs:  np.ndarray,
    lows:   np.ndarray,
    level:  float,
    is_support: bool,
) -> list[int]:
    """Return start bar indices of each touch episode of `level`.

    A touch = bar where price was within TOUCH_ZONE of level:
      support  → low <= level + TOUCH_ZONE  (price approaching from above)
      resistance → high >= level - TOUCH_ZONE (price approaching from below)
    Consecutive bars are grouped; new episode requires TOUCH_COOLDOWN bars of separation.
    """
    if is_support:
        near = lows <= level + TOUCH_ZONE
    else:
        near = highs >= level - TOUCH_ZONE

    episodes = []
    last_end = -TOUCH_COOLDOWN - 1

    i = 0
    n = len(near)
    while i < n:
        if near[i]:
            start = i
            # extend episode while still near
            while i < n and near[i]:
                i += 1
            end = i - 1

            # Only count as new episode if far enough from previous
            if start - last_end > TOUCH_COOLDOWN:
                episodes.append(start)
            last_end = end
        else:
            i += 1

    return episodes


# ── helper: extract context features at a touch bar ──────────────────────────

def extract_context_features(
    closes: np.ndarray,
    highs:  np.ndarray,
    lows:   np.ndarray,
    vols:   np.ndarray,
    times:  pd.DatetimeIndex,  # ET timestamps for each bar
    bar_idx: int,
    level: float,
    touch_count_today: int,
) -> dict:
    """Extract the 5 context feature groups at `bar_idx`."""
    i = bar_idx

    # ── 1. Touch count today ─────────────────────────────────────────────────
    touch_n = touch_count_today  # 0 = first touch

    # ── 2. Approach velocity ─────────────────────────────────────────────────
    look = APPROACH_LOOKBACK
    if i >= look:
        price_then = closes[i - look]
        price_now  = closes[i]
        approach_vel = (price_now - price_then) / look
    else:
        approach_vel = 0.0

    # How many bars to travel from 20pts away to touch zone
    # Walk backwards from i to find when price was 20pts away
    approach_bars = 0
    for k in range(1, min(i + 1, 120)):
        past = closes[i - k]
        if abs(past - level) > 20.0:
            approach_bars = k
            break

    # ── 3. Time of day ────────────────────────────────────────────────────────
    t = times[i]
    time_of_day_mins = t.hour * 60 + t.minute
    is_rth = RTH_OPEN_MIN <= time_of_day_mins < RTH_CLOSE_MIN

    # ── 4. Trend context ─────────────────────────────────────────────────────
    for lb, sfx in [(TREND_SHORT, '60'), (TREND_LONG, '240')]:
        pass  # computed below

    def trend_features(lookback, suffix):
        if i >= lookback:
            diff = closes[i] - closes[i - lookback]
        else:
            diff = closes[i] - closes[0] if i > 0 else 0.0
        return {
            f'trend_dir_{suffix}':      int(np.sign(diff)),
            f'trend_strength_{suffix}': round(abs(diff), 2),
        }

    tf = {}
    tf.update(trend_features(TREND_SHORT, '60'))
    tf.update(trend_features(TREND_LONG, '240'))

    # ── 5. Volume context ─────────────────────────────────────────────────────
    vol_lb = VOL_LOOKBACK
    if i >= vol_lb:
        vol_baseline = float(vols[i - vol_lb:i].mean()) or 1.0
    else:
        vol_baseline = float(vols[:i].mean()) if i > 0 else 1.0

    vol_at_touch   = float(vols[i])
    vol_zscore_touch    = (vol_at_touch - vol_baseline) / (vol_baseline + 1e-9)

    approach_start = max(0, i - look)
    approach_vols  = vols[approach_start:i]
    if len(approach_vols) > 0:
        vol_zscore_approach = float(
            (approach_vols.mean() - vol_baseline) / (vol_baseline + 1e-9)
        )
    else:
        vol_zscore_approach = 0.0

    # Volume drying: last 5 bars each lower than previous
    vol_drying = False
    if i >= 5:
        last5 = vols[i - 4:i + 1]
        vol_drying = bool(np.all(np.diff(last5.astype(float)) < 0))

    # ATR-like local volatility (mean of bar ranges, last 20 bars)
    r_start = max(0, i - vol_lb)
    ranges  = highs[r_start:i] - lows[r_start:i]
    atr_20  = round(float(ranges.mean()), 2) if len(ranges) > 0 else 0.0

    return {
        'touch_n_today':       touch_n,
        'approach_vel':        round(approach_vel, 3),
        'approach_bars':       approach_bars,
        'time_of_day_mins':    time_of_day_mins,
        'is_rth':              int(is_rth),
        **tf,
        'vol_zscore_touch':    round(vol_zscore_touch, 3),
        'vol_zscore_approach': round(vol_zscore_approach, 3),
        'vol_drying':          int(vol_drying),
        'atr_20':              atr_20,
    }


# ── helper: label outcomes at a touch bar ────────────────────────────────────

def label_outcomes(
    closes: np.ndarray,
    highs:  np.ndarray,
    lows:   np.ndarray,
    bar_idx: int,
    is_support: bool,
    level:  float,
) -> dict:
    """Measure forward price behavior from bar_idx."""
    i   = bar_idx
    n   = len(closes)
    ref = closes[i]

    out = {}

    for w in OUTCOME_WINDOWS:
        end    = min(i + w + 1, n)
        fwd_h  = highs [i + 1:end]
        fwd_l  = lows  [i + 1:end]
        fwd_c  = closes[i + 1:end]

        if len(fwd_c) == 0:
            out[f'max_fav_{w}']  = np.nan
            out[f'max_adv_{w}']  = np.nan
            out[f'win_{w}']      = np.nan
            continue

        if is_support:
            max_fav = float(fwd_h.max() - ref)
            max_adv = float(ref - fwd_l.min())
        else:
            max_fav = float(ref - fwd_l.min())
            max_adv = float(fwd_h.max() - ref)

        out[f'max_fav_{w}']  = round(max_fav, 2)
        out[f'max_adv_{w}']  = round(max_adv, 2)

        # Binary win: hit TARGET before STOP (bar-by-bar simulation)
        win = np.nan
        for j in range(len(fwd_c)):
            h = float(fwd_h[j]) if j < len(fwd_h) else ref
            l = float(fwd_l[j]) if j < len(fwd_l) else ref
            fav = (h - ref) if is_support else (ref - l)
            adv = (ref - l) if is_support else (h - ref)
            if fav >= TARGET_PTS:
                win = 1
                break
            if adv >= STOP_PTS:
                win = 0
                break

        out[f'win_{w}'] = win

    # Failed breakdown / failed breakout (supports only)
    if is_support:
        end_break   = min(i + BREAK_LOOKBACK + 1, n)
        end_reclaim = min(i + BREAK_LOOKBACK + RECLAIM_WINDOW + 1, n)
        fwd_c_break   = closes[i + 1:end_break]
        fwd_c_reclaim = closes[i + 1:end_reclaim]

        broke_below = bool(len(fwd_c_break) > 0 and np.any(fwd_c_break < level - TOUCH_ZONE))
        reclaimed   = False
        if broke_below and len(fwd_c_reclaim) > 0:
            # Find first bar that broke below, then see if price came back above
            for j, c in enumerate(fwd_c_reclaim):
                if c < level - TOUCH_ZONE:
                    # price broke — look for reclaim after this bar
                    reclaim_slice = fwd_c_reclaim[j + 1:]
                    if len(reclaim_slice) > 0 and np.any(reclaim_slice > level):
                        reclaimed = True
                    break
        out['broke_below']             = int(broke_below)
        out['reclaimed_after_break']   = int(reclaimed)
    else:
        out['broke_below']             = np.nan
        out['reclaimed_after_break']   = np.nan

    return out


# ── main loop ─────────────────────────────────────────────────────────────────

def build_dataset(start: str | None = None, end: str | None = None) -> pd.DataFrame:
    print("Loading 1-min cache...", flush=True)
    t0       = time.time()
    df1m     = _get_cache()   # UTC-indexed, 1-min bars
    df1m_et  = df1m.copy()
    df1m_et.index = df1m_et.index.tz_convert('America/New_York')
    print(f"  {len(df1m_et):,} bars loaded in {time.time()-t0:.1f}s", flush=True)

    print("Resampling to 15-min...", flush=True)
    df15_et = _resample_15m(df1m)   # ET-indexed 15-min

    # All arrays needed for level computation (15-min scope)
    highs_all_15 = df15_et['high'].values
    lows_all_15  = df15_et['low'].values
    vols_all_15  = df15_et['volume'].values

    print("Loading ML model...", flush=True)
    model = _load_ml_model()
    if model is None:
        print("  WARNING: ML model not found — ml_score will be None", flush=True)

    anchors = get_anchor_dates(df15_et, start, end)
    print(f"Anchor dates: {len(anchors)} (from {anchors[0].date()} to {anchors[-1].date()})", flush=True)

    # Pre-extract 1-min arrays for speed
    closes_1m = df1m_et['close'].values
    highs_1m  = df1m_et['high'].values
    lows_1m   = df1m_et['low'].values
    vols_1m   = df1m_et['volume'].values
    times_1m  = df1m_et.index

    all_rows: list[dict] = []
    n_anchors = len(anchors)

    # Pre-compute ET hour/minute arrays from 1-min index for fast RTH detection
    times_hm = times_1m.hour * 60 + times_1m.minute   # minutes-since-midnight ET

    for a_num, bar4pm_et in enumerate(anchors):
        if a_num % 10 == 0:
            pct = a_num / n_anchors * 100
            ta  = time.time()
            print(f"  {a_num}/{n_anchors} ({pct:.0f}%)  anchor={bar4pm_et.date()}"
                  f"  rows={len(all_rows):,}", flush=True)

        # ── compute levels for this anchor ────────────────────────────────────
        levels = compute_levels_for_anchor(
            df15_et, highs_all_15, lows_all_15, vols_all_15,
            bar4pm_et, model,
        )
        if not levels:
            continue

        # ── find 1-min bars for the session following this anchor ─────────────
        # Session: bar4pm_et  to  next 4pm ET (or end of data)
        # Use precomputed anchor list for O(1) next-anchor lookup
        next_anchor_idx = a_num + 1
        session_end = (anchors[next_anchor_idx] if next_anchor_idx < n_anchors
                       else times_1m[-1])

        session_mask = (times_1m > bar4pm_et) & (times_1m <= session_end)
        session_idx  = np.where(session_mask)[0]

        if len(session_idx) < 10:
            continue

        # Slice session arrays (with lookback buffer)
        buf_start = max(0, session_idx[0] - TREND_LONG - 10)
        buf_end   = min(len(closes_1m), session_idx[-1] + OUTCOME_WINDOWS[-1] + 10)

        s_closes = closes_1m[buf_start:buf_end]
        s_highs  = highs_1m [buf_start:buf_end]
        s_lows   = lows_1m  [buf_start:buf_end]
        s_vols   = vols_1m  [buf_start:buf_end]
        s_times  = times_1m [buf_start:buf_end]
        s_hm     = times_hm [buf_start:buf_end]  # minutes-since-midnight slice

        # Index offsets: session_idx[0] - buf_start = session start in s_* arrays
        sess_start_in_s = session_idx[0] - buf_start
        sess_end_in_s   = min(session_idx[-1] - buf_start + 1, len(s_closes))

        # Day-open: first RTH close for this session (computed once per anchor)
        sess_hm     = s_hm[sess_start_in_s:sess_end_in_s]
        rth_in_sess = np.where((sess_hm >= RTH_OPEN_MIN) & (sess_hm < RTH_CLOSE_MIN))[0]
        sess_closes = s_closes[sess_start_in_s:sess_end_in_s]
        day_open    = float(sess_closes[rth_in_sess[0]]) if len(rth_in_sess) > 0 \
                      else float(sess_closes[0])

        # ── scan each level for touch episodes ────────────────────────────────
        for lv in levels:
            level_price = float(lv['price'])
            is_support  = not lv['is_res']

            sess_highs = s_highs[sess_start_in_s:sess_end_in_s]
            sess_lows  = s_lows [sess_start_in_s:sess_end_in_s]

            episode_starts = find_touch_episodes(
                sess_closes, sess_highs, sess_lows, level_price, is_support
            )

            gap_pts = round(day_open - lv['close4pm'], 2)

            touch_count_today = 0
            for ep_start_in_sess in episode_starts:
                # Absolute index in the s_* buffer
                abs_idx = sess_start_in_s + ep_start_in_sess

                # Need enough lookback AND forward bars
                if abs_idx < TREND_LONG:
                    touch_count_today += 1
                    continue
                if abs_idx + OUTCOME_WINDOWS[-1] + 5 >= len(s_closes):
                    break  # near end of buffer — skip rest of this level

                ctx = extract_context_features(
                    s_closes, s_highs, s_lows, s_vols, s_times,
                    abs_idx, level_price, touch_count_today,
                )
                out = label_outcomes(
                    s_closes, s_highs, s_lows,
                    abs_idx, is_support, level_price,
                )

                row = {
                    'anchor_date':   bar4pm_et.date().isoformat(),
                    'touch_time':    s_times[abs_idx].isoformat(),
                    'level_price':   level_price,
                    'is_support':    int(is_support),
                    # Level features
                    'ml_score':              lv.get('ml_score'),
                    'is_major':              int(lv.get('is_major', False)),
                    'sr_flip':               lv.get('sr_flip', 0),
                    'dist_from_4pm':         lv.get('dist_from_4pm', 0),
                    'historical_touches':    lv.get('historical_touches', 0),
                    'days_since_pivot':      lv.get('days_since_pivot', 0),
                    'recency_rank':          lv.get('recency_rank', 0),
                    'local_density':         lv.get('local_density', 0),
                    'is_mult5':              lv.get('is_mult5', 0),
                    'dist_round':            lv.get('dist_round', 0),
                    'historical_bounce':     lv.get('historical_bounce', 0),
                    'price_crossings':       lv.get('price_crossings', 0),
                    'is_ath_cluster':        int(lv.get('_ath_cluster', False)),
                    'close4pm':              lv.get('close4pm', 0),
                    # Context features
                    **ctx,
                    # Session context
                    'day_open':              day_open,
                    'dist_from_open':        round(level_price - day_open, 2),
                    'gap_pts':               gap_pts,
                    # Outcomes
                    **out,
                }
                all_rows.append(row)
                touch_count_today += 1

    print(f"\nDone. {len(all_rows):,} touch events from {n_anchors} anchor dates.", flush=True)

    df = pd.DataFrame(all_rows)

    # Coerce numeric types
    float_cols = [c for c in df.columns if df[c].dtype == object]
    for c in float_cols:
        try:
            df[c] = pd.to_numeric(df[c])
        except (ValueError, TypeError):
            pass

    return df


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Build level-touch events dataset')
    parser.add_argument('--start', default=None, help='Start date YYYY-MM-DD')
    parser.add_argument('--end',   default=None, help='End date YYYY-MM-DD')
    parser.add_argument('--out',   default=str(OUT_DIR / 'touch_events.parquet'),
                        help='Output parquet path')
    args = parser.parse_args()

    t0 = time.time()
    df = build_dataset(start=args.start, end=args.end)

    out_path = Path(args.out)
    df.to_parquet(out_path, index=False)
    elapsed = time.time() - t0
    print(f"Saved {len(df):,} rows -> {out_path}  ({elapsed:.0f}s total)", flush=True)
    print(f"\nColumn overview:", flush=True)
    print(df.dtypes.to_string(), flush=True)
    print(f"\nWin rates (win_30 where defined):", flush=True)
    if 'win_30' in df.columns:
        w = df['win_30'].dropna()
        print(f"  Overall: {w.mean():.1%}  (n={len(w):,})", flush=True)
        if 'is_support' in df.columns:
            for s, label in [(1, 'supports'), (0, 'resistances')]:
                sub = df[df['is_support'] == s]['win_30'].dropna()
                print(f"  {label}: {sub.mean():.1%}  (n={len(sub):,})", flush=True)
