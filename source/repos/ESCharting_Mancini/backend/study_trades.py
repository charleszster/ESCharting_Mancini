"""
study_trades.py — API endpoint serving filtered study trade events from the edge study dataset.

GET /study-trades
  date_from   YYYY-MM-DD  filter by anchor_date
  date_to     YYYY-MM-DD  filter by anchor_date
  setup       comma-separated: afternoon_ft, fb_afternoon, fb_opening
  result      all | win | loss

Returns JSON: { trades: [...], total: N }
"""

from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import APIRouter, Query

router = APIRouter()

PARQUET_PATH = Path(__file__).parent.parent / 'research' / 'edge_study' / 'data' / 'touch_events.parquet'

_df_cache: pd.DataFrame | None = None


def _load():
    global _df_cache
    if _df_cache is not None:
        return _df_cache
    if not PARQUET_PATH.exists():
        return None
    df = pd.read_parquet(PARQUET_PATH)
    # Pre-compute UTC unix timestamp for chart positioning
    df['touch_ts'] = (
        pd.to_datetime(df['touch_time'], utc=True).astype('int64') // 10 ** 9
    )
    _df_cache = df
    return df


def _build_subset(df: pd.DataFrame, setup: str) -> pd.DataFrame | None:
    if setup == 'afternoon_ft':
        mask = (
            (df['touch_n_today'] == 0) &
            (df['time_of_day_mins'] >= 930) &
            (df['is_rth'] == 1)
        )
        sub = df[mask].copy()
        sub['setup_type'] = 'afternoon_ft'
        sub['outcome'] = sub['win_30']
        return sub

    if setup == 'fb_afternoon':
        mask = (
            (df['is_support'] == 1) &
            (df['broke_below'] == 1) &
            (df['reclaimed_after_break'].notna()) &
            (df['time_of_day_mins'] >= 870) &
            (df['time_of_day_mins'] < 960) &
            (df['is_rth'] == 1)
        )
        sub = df[mask].copy()
        sub['setup_type'] = 'fb_afternoon'
        sub['outcome'] = sub['reclaimed_after_break']
        return sub

    if setup == 'fb_opening':
        mask = (
            (df['is_support'] == 1) &
            (df['broke_below'] == 1) &
            (df['reclaimed_after_break'].notna()) &
            (df['time_of_day_mins'] >= 570) &
            (df['time_of_day_mins'] < 600) &
            (df['is_rth'] == 1)
        )
        sub = df[mask].copy()
        sub['setup_type'] = 'fb_opening'
        sub['outcome'] = sub['reclaimed_after_break']
        return sub

    return None


@router.get('/study-trades')
def get_study_trades(
    date_from: str | None = Query(default=None),
    date_to:   str | None = Query(default=None),
    setup:     str        = Query(default='afternoon_ft,fb_afternoon'),
    result:    str        = Query(default='all'),
):
    df = _load()
    if df is None:
        return {'trades': [], 'total': 0, 'error': 'Dataset not found. Run build_dataset.py first.'}

    # Date filter
    filtered = df
    if date_from:
        filtered = filtered[filtered['anchor_date'] >= date_from]
    if date_to:
        filtered = filtered[filtered['anchor_date'] <= date_to]

    # Build requested setups
    parts = []
    for s in [x.strip() for x in setup.split(',') if x.strip()]:
        sub = _build_subset(filtered, s)
        if sub is not None:
            parts.append(sub)

    if not parts:
        return {'trades': [], 'total': 0}

    combined = pd.concat(parts, ignore_index=True)

    # Result filter
    if result == 'win':
        combined = combined[combined['outcome'] == 1]
    elif result == 'loss':
        combined = combined[combined['outcome'] == 0]
    # 'all' keeps resolved + unresolved

    combined = combined.sort_values('touch_ts')

    def _safe(v):
        if v is None:
            return None
        try:
            if np.isnan(v):
                return None
        except Exception:
            pass
        return v

    trades = []
    for row in combined.itertuples(index=False):
        trades.append({
            'touch_time':      row.touch_time,
            'touch_ts':        int(row.touch_ts),
            'anchor_date':     str(row.anchor_date),
            'level_price':     float(row.level_price),
            'is_support':      int(row.is_support),
            'setup_type':      row.setup_type,
            'outcome':         _safe(row.outcome),
            'ml_score':        _safe(row.ml_score),
            'is_major':        int(row.is_major),
            'sr_flip':         int(row.sr_flip),
            'touch_n_today':   int(row.touch_n_today),
            'time_of_day_mins': int(row.time_of_day_mins),
        })

    return {'trades': trades, 'total': len(trades)}
