"""
Phase 6: Feature matrix builder for ML pivot quality classifier.

For each trading day, extracts ALL raw pivot candidates (before dedup)
and computes per-candidate features. Labels each candidate 1/0 based on
whether it matches a Mancini level within ±MATCH_TOL pts.

Phase 6c additions:
  - max_pivot_age_days: recency filter — skip pivots older than N days
  - top_n_per_window: significance filter — keep only top N pivots by swing
    quality (prominence * bounce) per lookback window, discard the rest
  - Improved sr_flip: uses confirmed pivot arrays instead of raw bar h/l

Usage:
    from feature_builder import build_feature_matrix
    # Baseline (no filtering):
    df = build_feature_matrix()
    # Recency filter only:
    df = build_feature_matrix(max_pivot_age_days=365)
    # Significance filter only:
    df = build_feature_matrix(top_n_per_window=50)
    # Both combined:
    df = build_feature_matrix(max_pivot_age_days=365, top_n_per_window=50)
"""

import re
import sqlite3
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).parent.parent

from data_manager import _get_cache
from auto_levels import _resample_15m, _find_4pm_bar, _find_pivots

# ── constants ──────────────────────────────────────────────────────────────────

PIVOT_LEN      = 5        # bars each side for pivot confirmation
PRICE_RANGE    = 325.0    # ±pts from close4pm
TOUCH_ZONE     = 2.0      # ±pts for touch counting
FORWARD_BARS   = 10       # bars forward for bounce + clean_departure
DENSITY_ZONE   = 10.0     # ±pts for local_pivot_density
CONSOL_ZONE    = 3.0      # ±pts for consolidation_time
MATCH_TOL      = 2.0      # pts — candidate matches Mancini if within this distance
DATE_FROM      = "2025-03-07"

# ── Mancini parsing ────────────────────────────────────────────────────────────

def _parse_price_token(tok):
    tok = tok.strip().strip(',')
    m = re.match(r'^(\d+)-(\d+)$', tok)
    if m:
        a, b_raw = m.group(1), m.group(2)
        b = (a[:len(a) - len(b_raw)] + b_raw) if len(b_raw) < len(a) else b_raw
        return (float(a) + float(b)) / 2
    return float(tok)

def _parse_mancini(text):
    if not text:
        return []
    clean = re.sub(r'\s*\(major\)', '', text)
    out = []
    for part in clean.split(','):
        part = part.strip()
        if part:
            try:
                out.append(_parse_price_token(part))
            except Exception:
                pass
    return sorted(out)

# ── feature helpers ────────────────────────────────────────────────────────────

def _round_number_distances(price):
    """Distance to nearest multiple of 5, 25, 50, 100 pts."""
    d5   = price % 5;   d5   = min(d5, 5   - d5)
    d25  = price % 25;  d25  = min(d25, 25  - d25)
    d50  = price % 50;  d50  = min(d50, 50  - d50)
    d100 = price % 100; d100 = min(d100, 100 - d100)
    return d5, d25, d50, d100

def _sr_flip_and_crossings(highs, lows, closes, idx, price, ptype,
                           ph_prices, pl_prices, zone=2.0):
    """
    S/R flip: did this level previously serve the opposite role?
    Uses confirmed pivot arrays (ph_prices, pl_prices) instead of raw bar h/l
    to reduce false positives.

    - pivot high (resistance): did a confirmed pivot LOW previously exist near
      this price? (prior support that has now become resistance)
    - pivot low (support): did a confirmed pivot HIGH previously exist near
      this price? (prior resistance that has now become support)

    Also counts close-crossings: how many times did closes straddle this level.
    """
    segment_c = closes[:idx]

    if ptype == 'high':
        # Look for prior confirmed pivot lows near this price
        sr_flip = int(len(pl_prices) > 0 and np.any(np.abs(pl_prices - price) <= zone))
    else:
        # Look for prior confirmed pivot highs near this price
        sr_flip = int(len(ph_prices) > 0 and np.any(np.abs(ph_prices - price) <= zone))

    # Price crossings: consecutive closes that straddle the level
    crossings = 0
    if len(segment_c) > 1:
        above = segment_c > price
        crossings = int(np.sum(np.diff(above.astype(int)) != 0))

    return sr_flip, crossings


def _pivot_swing_quality(highs, lows, idx, ptype, n, forward_bars):
    """Composite quality score for significance filtering: prominence * bounce."""
    prom = _prominence(highs, lows, idx, ptype, n)
    end = min(idx + forward_bars + 1, len(highs))
    fwd_h = highs[idx + 1:end]
    fwd_l = lows[idx + 1:end]
    if ptype == 'high':
        bounce = float(highs[idx] - fwd_l.min()) if len(fwd_l) > 0 else 0.0
    else:
        bounce = float(fwd_h.max() - lows[idx]) if len(fwd_h) > 0 else 0.0
    return prom * bounce

def _prominence(highs, lows, idx, ptype, n):
    """How much the pivot stands above (high) or below (low) its N neighbours."""
    lo = max(0, idx - n)
    hi = min(len(highs), idx + n + 1)
    if ptype == 'high':
        neighbours = np.concatenate([highs[lo:idx], highs[idx + 1:hi]])
        return float(highs[idx] - neighbours.max()) if len(neighbours) else 0.0
    else:
        neighbours = np.concatenate([lows[lo:idx], lows[idx + 1:hi]])
        return float(neighbours.min() - lows[idx]) if len(neighbours) else 0.0

def _consolidation_time(highs, lows, idx, price, zone, lookback=50):
    """Count consecutive bars immediately before pivot that overlap ±zone of price."""
    count = 0
    for k in range(1, min(idx, lookback) + 1):
        i = idx - k
        if lows[i] <= price + zone and highs[i] >= price - zone:
            count += 1
        else:
            break
    return count

def _clean_departure(highs, lows, idx, price, ptype, n_bars):
    """Magnitude of move away from level in first n_bars after pivot."""
    end = min(idx + n_bars + 1, len(highs))
    fwd_h = highs[idx + 1:end]
    fwd_l = lows[idx + 1:end]
    if len(fwd_l) == 0:
        return 0.0
    if ptype == 'high':
        return float(price - fwd_l.min())   # drop away from high
    else:
        return float(fwd_h.max() - price)   # rise away from low

def _trading_days_since(anchor_et, pivot_et, trading_dates_set):
    """Approximate trading days between pivot bar and anchor bar."""
    if pivot_et >= anchor_et:
        return 0
    # count calendar days and scale roughly (252/365)
    delta = (anchor_et.date() - pivot_et.date()).days
    return int(round(delta * 252 / 365))

# ── main builder ───────────────────────────────────────────────────────────────

def build_feature_matrix(verbose=True,
                         max_pivot_age_days=None,
                         top_n_per_window=None,
                         window_bars=None):
    """
    Returns a DataFrame with one row per (trading_date, pivot_candidate).
    Columns: all features + 'label' (1 = matches Mancini, 0 = doesn't).

    Parameters
    ----------
    max_pivot_age_days : int or None
        Recency filter. If set, only include pivots from the last N calendar days
        before the 4pm anchor. E.g. 365 = last year only.
    top_n_per_window : int or None
        Significance filter. If set, keep only the top N pivot highs and top N
        pivot lows by swing quality (prominence * bounce) within the historical
        slice. Reduces pool from ~1000 to 2*N candidates before price_range filter.
    window_bars : int or None
        Forward window for bounce used in significance scoring. Defaults to
        FORWARD_BARS if None.
    """
    df_cache = _get_cache()
    df15 = _resample_15m(df_cache)

    sig_window = window_bars if window_bars is not None else FORWARD_BARS

    # Pre-extract numpy arrays for fast indexing
    highs_all = df15['high'].values
    lows_all  = df15['low'].values
    vols_all  = df15['volume'].values
    ts_all    = df15.index  # ET-timezone Timestamps

    # Load Mancini levels
    conn = sqlite3.connect(ROOT / 'data' / 'levels.db')
    rows = conn.execute(
        "SELECT trading_date, supports, resistances FROM levels "
        "WHERE trading_date >= ? ORDER BY trading_date", (DATE_FROM,)
    ).fetchall()
    conn.close()

    all_rows = []
    skipped  = 0

    for di, (td, ms, mr) in enumerate(rows):
        close4pm, bar4pm_et = _find_4pm_bar(df15, td)
        if close4pm is None:
            skipped += 1
            continue

        # Mancini labels for this date
        man_levels = _parse_mancini(ms) + _parse_mancini(mr)
        man_arr    = np.array(man_levels) if man_levels else np.array([])

        # Historical slice (at or before 4pm anchor)
        hist_mask   = df15.index <= bar4pm_et
        df15_hist   = df15[hist_mask]
        n_hist      = len(df15_hist)
        highs_hist  = df15_hist['high'].values
        lows_hist   = df15_hist['low'].values

        # Find pivots in historical slice
        ph_idx, ph_p, pl_idx, pl_p = _find_pivots(highs_hist, lows_hist, PIVOT_LEN)

        # ── Recency filter ────────────────────────────────────────────────────
        # Drop pivots older than max_pivot_age_days calendar days before anchor.
        if max_pivot_age_days is not None:
            cutoff_et = bar4pm_et - pd.Timedelta(days=max_pivot_age_days)
            ph_keep = np.array(ts_all[ph_idx] >= cutoff_et, dtype=bool)
            pl_keep = np.array(ts_all[pl_idx] >= cutoff_et, dtype=bool)
            ph_idx = ph_idx[ph_keep]; ph_p = ph_p[ph_keep]
            pl_idx = pl_idx[pl_keep]; pl_p = pl_p[pl_keep]

        # ── Significance filter ───────────────────────────────────────────────
        # Keep only top_n_per_window pivot highs and lows by swing quality.
        if top_n_per_window is not None and top_n_per_window > 0:
            if len(ph_idx) > top_n_per_window:
                scores_h = np.array([
                    _pivot_swing_quality(highs_hist, lows_hist, i, 'high', PIVOT_LEN, sig_window)
                    for i in ph_idx
                ])
                top_h = np.argsort(scores_h)[-top_n_per_window:]
                ph_idx = ph_idx[top_h]; ph_p = ph_p[top_h]
            if len(pl_idx) > top_n_per_window:
                scores_l = np.array([
                    _pivot_swing_quality(highs_hist, lows_hist, i, 'low', PIVOT_LEN, sig_window)
                    for i in pl_idx
                ])
                top_l = np.argsort(scores_l)[-top_n_per_window:]
                pl_idx = pl_idx[top_l]; pl_p = pl_p[top_l]

        # Collect all candidates within price_range
        candidates = []
        for idx, price in zip(ph_idx, ph_p):
            if abs(float(price) - close4pm) <= PRICE_RANGE:
                candidates.append((int(idx), float(price), 'high'))
        for idx, price in zip(pl_idx, pl_p):
            if abs(float(price) - close4pm) <= PRICE_RANGE:
                candidates.append((int(idx), float(price), 'low'))

        if not candidates:
            continue

        all_prices  = np.array([c[1] for c in candidates])
        closes_hist = df15_hist['close'].values

        # Per-day average volume for normalisation
        day_vol_mean = float(vols_all[hist_mask].mean()) or 1.0

        # Touch arrays (all historical pivots, not just in price_range)
        touch_ph_p = ph_p
        touch_pl_p = pl_p

        for (cidx, price, ptype) in candidates:
            p_rounded = round(price)

            # ── label ────────────────────────────────────────────────────────
            if len(man_arr) > 0:
                label = int(np.min(np.abs(man_arr - p_rounded)) <= MATCH_TOL)
            else:
                label = 0

            # ── bounce ───────────────────────────────────────────────────────
            # Uses global index (hist slice index == global index since df15_hist
            # is a prefix of df15)
            end   = min(cidx + FORWARD_BARS + 1, len(highs_all))
            fwd_h = highs_all[cidx + 1:end]
            fwd_l = lows_all[cidx + 1:end]
            if ptype == 'high':
                bounce = float(price - fwd_l.min()) if len(fwd_l) > 0 else 0.0
            else:
                bounce = float(fwd_h.max() - price) if len(fwd_h) > 0 else 0.0

            # ── touches ──────────────────────────────────────────────────────
            touches = (
                int(np.sum(np.abs(touch_ph_p - price) <= TOUCH_ZONE)) +
                int(np.sum(np.abs(touch_pl_p - price) <= TOUCH_ZONE))
            )

            # ── local_pivot_density ───────────────────────────────────────────
            density = int(np.sum(np.abs(all_prices - price) <= DENSITY_ZONE)) - 1

            # ── volume at pivot (z-score vs day mean) ─────────────────────────
            vol_raw     = float(vols_all[cidx])
            vol_zscore  = (vol_raw - day_vol_mean) / (day_vol_mean + 1e-9)

            # ── prominence ────────────────────────────────────────────────────
            prom = _prominence(highs_hist, lows_hist, cidx, ptype, PIVOT_LEN)

            # ── consolidation_time ────────────────────────────────────────────
            consol = _consolidation_time(highs_hist, lows_hist, cidx, price, CONSOL_ZONE)

            # ── clean_departure ───────────────────────────────────────────────
            depart = _clean_departure(highs_all, lows_all, cidx, price, ptype, FORWARD_BARS)

            # ── S/R flip + price crossings ────────────────────────────────────
            # Use confirmed pivot arrays (not raw bars) for cleaner sr_flip signal
            sr_flip, crossings = _sr_flip_and_crossings(
                highs_hist, lows_hist, closes_hist, cidx, price, ptype,
                ph_prices=ph_p, pl_prices=pl_p,
            )

            # ── round-number distances ────────────────────────────────────────
            d5, d25, d50, d100 = _round_number_distances(price)
            is_mult5 = int(p_rounded % 5 == 0)
            # distance from rounded integer to nearest mult-of-5
            r_mod5 = p_rounded % 5
            dist_round_to_mult5 = min(r_mod5, 5 - r_mod5)

            # ── days since pivot ──────────────────────────────────────────────
            pivot_et      = ts_all[cidx]
            days_since    = _trading_days_since(bar4pm_et, pivot_et, None)

            # ── distance / direction ──────────────────────────────────────────
            dist_from_4pm = abs(price - close4pm)
            is_support    = int(price < close4pm)
            is_high_piv   = int(ptype == 'high')

            # ── recency rank (0 = most recent) ────────────────────────────────
            recency_rank  = n_hist - 1 - cidx   # bars before anchor

            all_rows.append({
                'trading_date':         td,
                'price':                price,
                'price_rounded':        p_rounded,
                'pivot_type':           is_high_piv,
                'is_support':           is_support,
                # core quality signals
                'bounce':               round(bounce, 2),
                'touches':              touches,
                'local_density':        density,
                'prominence':           round(prom, 2),
                'vol_zscore':           round(vol_zscore, 3),
                'consolidation':        consol,
                'clean_departure':      round(depart, 2),
                # S/R structure
                'sr_flip':              sr_flip,
                'price_crossings':      crossings,
                # price structure
                'dist_from_4pm':        round(dist_from_4pm, 2),
                'dist_d5':              round(d5, 2),
                'dist_d25':             round(d25, 2),
                'dist_d50':             round(d50, 2),
                'dist_d100':            round(d100, 2),
                'is_mult5':             is_mult5,
                'dist_round_to_mult5':  dist_round_to_mult5,
                # temporal
                'days_since_pivot':     days_since,
                'recency_rank':         recency_rank,
                # label
                'label':                label,
            })

        if verbose and (di + 1) % 20 == 0:
            pos = sum(1 for r in all_rows[-len(candidates):] if r['label'])
            print(f"  {di+1}/{len(rows)}  {td}  candidates={len(candidates)}  "
                  f"matches={pos}  total_rows={len(all_rows)}", flush=True)

    df = pd.DataFrame(all_rows)
    if verbose:
        n_pos = df['label'].sum()
        print(f"\nFeature matrix: {len(df):,} rows  |  "
              f"positive={n_pos:,} ({n_pos/len(df)*100:.1f}%)  |  "
              f"skipped_dates={skipped}")
    return df


if __name__ == '__main__':
    from data_manager import warm_cache
    print("Warming cache...")
    warm_cache()
    print("Building feature matrix...")
    df = build_feature_matrix(verbose=True)

    out = ROOT / 'data' / 'phase6_features.parquet'
    df.to_parquet(out, index=False)
    print(f"Saved: {out}  ({out.stat().st_size // 1024} KB)")
    print(df.dtypes)
    print(df.head(3).to_string())
