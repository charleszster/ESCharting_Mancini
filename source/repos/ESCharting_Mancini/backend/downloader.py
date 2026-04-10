"""
Databento download, TradingView CSV import, parquet append, and cache-rebuild helpers.
Called by the /download/* and /import/* endpoints in main.py.
"""
import asyncio
import json
import os
import re as _re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

PARQUET_1M = Path(__file__).parent.parent / "data" / "es_1m.parquet"
PARQUET_FM = Path(__file__).parent.parent / "data" / "es_front_month.parquet"

DATASET = "GLBX.MDP3"
SCHEMA  = "ohlcv-1m"
SYMBOLS = ["ES.FUT"]
STYPE   = "parent"

# One worker so concurrent downloads don't stomp on each other
_executor = ThreadPoolExecutor(max_workers=1)

# Symbol normalisation: Databento API may return 2-digit-year symbols (ESH26)
# while the existing parquet + roll calendar use 1-digit-year (ESH6).
_SYM_RE = _re.compile(r"^(ES[HMUZ])(\d{2,})$")


def _normalize_symbol(sym: str) -> str:
    m = _SYM_RE.match(sym)
    if m:
        return m.group(1) + str(int(m.group(2)) % 10)
    return sym


def _client():
    import databento as db
    key = os.getenv("DATABENTO_API_KEY")
    if not key:
        raise ValueError("DATABENTO_API_KEY not set in .env")
    return db.Historical(key)


# ── Sync helpers (run in thread executor) ─────────────────────────────────────

# Databento's 422 error for exceeding available data includes the actual
# available end timestamp.  We parse it and retry rather than relying on
# get_dataset_range(), which returns a conservative (stale) value.
# Matches two Databento error formats:
#   422: "available up to '2026-04-09 21:00:00+00:00'"
#   422: "end time before 2026-04-09T13:15:49.396997000Z"
_AVAIL_END_RE = _re.compile(r"available up to '([^']+)'|end time before (\S+)")


def _desired_end(end: str) -> str:
    """Add 1 day to make the user-supplied ET date inclusive (Databento end is exclusive)."""
    from datetime import date, timedelta
    return pd.Timestamp(date.fromisoformat(end) + timedelta(days=1), tz="UTC").isoformat()


def _resolve_end(fn_try, end_str: str, label: str):
    """
    Call fn_try(end) up to 4 times, each time backing off from the
    Databento-reported limit.  Returns fn_try's result on success.
    """
    current = end_str
    for attempt in range(4):
        print(f"[{label}] attempt {attempt + 1} end={current!r}")
        try:
            return fn_try(current)
        except Exception as exc:
            exc_str = str(exc)
            m = _AVAIL_END_RE.search(exc_str)
            if m:
                raw     = (m.group(1) or m.group(2)).rstrip('.,;')
                avail   = pd.Timestamp(raw) - pd.Timedelta(minutes=1)
                current = avail.strftime('%Y-%m-%dT%H:%M:%SZ')
                print(f"[{label}] got limit, next end={current!r}")
            else:
                print(f"[{label}] no parseable limit — raising")
                raise
    raise RuntimeError(f"[{label}] gave up after 4 attempts (last end={current!r})")


def _get_estimate_sync(start: str, end: str) -> dict:
    """start may be an ET calendar date or an exact UTC timestamp."""
    client = _client()

    def _try(e):
        cost = client.metadata.get_cost(
            dataset=DATASET, symbols=SYMBOLS, stype_in=STYPE,
            schema=SCHEMA, start=start, end=e,
        )
        size = client.metadata.get_billable_size(
            dataset=DATASET, symbols=SYMBOLS, stype_in=STYPE,
            schema=SCHEMA, start=start, end=e,
        )
        return {"cost_usd": float(cost), "size_bytes": int(size)}

    return _resolve_end(_try, _desired_end(end), "estimate")


def _download_sync(start: str, end: str) -> pd.DataFrame:
    """start may be an ET calendar date (YYYY-MM-DD) or an exact UTC timestamp
    (e.g. 2026-04-09T23:00:00Z).  end is always an ET calendar date."""
    client = _client()

    def _try(e):
        return client.timeseries.get_range(
            dataset=DATASET, symbols=SYMBOLS, stype_in=STYPE,
            schema=SCHEMA, start=start, end=e,
        ).to_df()

    return _resolve_end(_try, _desired_end(end), "download")


def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalise a Databento to_df() result to match es_1m.parquet schema:
      - ts_event as datetime64[ns, UTC] column (not index)
      - open/high/low/close as float dollars (not fixed-point ints)
      - symbol in 1-digit-year format (ESH6, not ESH26)
    """
    # Move ts_event from index to column if needed
    if df.index.name == "ts_event":
        df = df.reset_index()

    # Ensure ts_event is datetime64[ns, UTC]
    if "ts_event" in df.columns:
        df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True)

    # Prices: older databento-python returns fixed-point int64 (price * 1e9);
    # newer versions return float. ES prices are ~4000–6000 so anything >1e6
    # indicates fixed-point encoding.
    for col in ("open", "high", "low", "close"):
        if col in df.columns and (
            pd.api.types.is_integer_dtype(df[col]) and df[col].max() > 1_000_000
        ):
            df[col] = df[col].astype(float) / 1e9

    # Normalise symbol format (ESH26 -> ESH6)
    if "symbol" in df.columns:
        df["symbol"] = df["symbol"].map(_normalize_symbol)

    keep = ["ts_event", "open", "high", "low", "close", "volume", "symbol"]
    return df[[c for c in keep if c in df.columns]].copy()


def _append_to_parquet(df: pd.DataFrame) -> int:
    """Append new rows to es_1m.parquet, dedup on ts_event + symbol."""
    df = _normalize_df(df)
    existing = pd.read_parquet(PARQUET_1M)

    # Ensure both sides have the same ts_event dtype for dedup
    if not pd.api.types.is_datetime64_any_dtype(existing["ts_event"]):
        existing["ts_event"] = pd.to_datetime(existing["ts_event"], utc=True)

    before = len(existing)
    combined = pd.concat([existing, df], ignore_index=True)
    combined = combined.drop_duplicates(subset=["ts_event", "symbol"])
    combined = combined.sort_values("ts_event").reset_index(drop=True)
    combined.to_parquet(PARQUET_1M, index=False)
    return len(combined) - before


def _rebuild_cache() -> None:
    """Delete the pre-processed front-month parquet and re-warm the cache."""
    if PARQUET_FM.exists():
        PARQUET_FM.unlink()
    from data_manager import warm_cache
    warm_cache()


# ── Public API ────────────────────────────────────────────────────────────────

def get_estimate(start: str, end: str) -> dict:
    return _get_estimate_sync(start, end)


def import_tv_csv(csv_bytes: bytes) -> dict:
    """
    Parse a TradingView 1-min OHLC CSV export and append to es_1m.parquet.

    TV export format: time, open, high, low, close  (no volume).
    Timestamps are ISO-8601 with UTC offset (e.g. 2026-04-09T16:00:00-04:00).
    Volume is set to 0 for all imported rows.
    The correct ES front-month symbol is assigned from the roll calendar.
    Existing rows are deduped — nothing is overwritten.
    """
    import io
    from data_manager import build_roll_calendar

    df = pd.read_csv(io.BytesIO(csv_bytes))
    required = {'time', 'open', 'high', 'low', 'close'}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"CSV missing columns: {missing}")

    df['ts_event'] = pd.to_datetime(df['time'], utc=True)
    df['volume']   = 0

    # Assign front-month ES symbol using the roll calendar.
    # For each timestamp, the active symbol is the one whose roll_ts is
    # most recent at or before that timestamp (rolls are sorted ascending).
    rolls   = build_roll_calendar()
    symbols = pd.Series('', index=df.index)
    for roll_ts, sym in rolls:
        symbols[df['ts_event'] >= roll_ts] = sym
    df['symbol'] = symbols
    df = df[df['symbol'] != ''].copy()
    if df.empty:
        raise ValueError("No rows fall within the known roll calendar range")

    csv_rows = len(df)
    new_rows = _append_to_parquet(df)
    _rebuild_cache()

    last_ts = df['ts_event'].max()
    if hasattr(last_ts, 'tzinfo') and last_ts.tzinfo is None:
        last_ts = last_ts.tz_localize('UTC')
    end_date = pd.Timestamp(last_ts).tz_convert('UTC').strftime('%Y-%m-%d')

    return {'new_rows': new_rows, 'csv_rows': csv_rows, 'end_date': end_date}


async def stream_download(start: str, end: str):
    """
    Async generator that yields SSE-formatted JSON strings.
    Stages: connect → download → append → rebuild → done (or error).
    """
    loop = asyncio.get_event_loop()

    def msg(type_: str, text: str, **extra) -> str:
        return f"data: {json.dumps({'type': type_, 'msg': text, **extra})}\n\n"

    try:
        yield msg("progress", "Connecting to Databento...")

        yield msg("progress", f"Downloading ES futures {start} to {end}...")
        df = await loop.run_in_executor(_executor, _download_sync, start, end)
        n_rows = len(df)

        # Capture last timestamp before we hand df off to the append worker
        ts_col = df.index if df.index.name == "ts_event" else df.get("ts_event")
        if ts_col is not None and len(ts_col) > 0:
            last = pd.Timestamp(ts_col.max())
            if last.tzinfo is None:
                last = last.tz_localize("UTC")
            new_end    = last.tz_convert("UTC").strftime("%Y-%m-%d")
            new_end_ts = last.strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            new_end    = end
            new_end_ts = None

        yield msg("progress", f"Downloaded {n_rows:,} rows. Appending to parquet...")
        new_rows = await loop.run_in_executor(_executor, _append_to_parquet, df)

        yield msg("progress", f"Added {new_rows:,} new rows. Rebuilding front-month cache (~30s)...")
        await loop.run_in_executor(_executor, _rebuild_cache)

        yield msg("done",
                  f"Done — {new_rows:,} new rows through {new_end}",
                  end_date=new_end,
                  end_ts=new_end_ts)

    except Exception as e:
        yield msg("error", str(e))
