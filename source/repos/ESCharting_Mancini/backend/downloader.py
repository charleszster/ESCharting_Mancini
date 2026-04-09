"""
Databento download, parquet append, and cache-rebuild helpers.
Called by the /download/* endpoints in main.py.
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
_AVAIL_END_RE = _re.compile(r"available up to '([^']+)'")


def _desired_end(end: str) -> str:
    """Add 1 day to make the user-supplied ET date inclusive (Databento end is exclusive)."""
    from datetime import date, timedelta
    return pd.Timestamp(date.fromisoformat(end) + timedelta(days=1), tz="UTC").isoformat()


def _get_estimate_sync(start: str, end: str) -> dict:
    """
    Try the desired end; if Databento rejects it, parse the actual available
    end from the error message and retry.
    """
    client  = _client()
    end_str = _desired_end(end)

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

    try:
        return _try(end_str)
    except Exception as exc:
        m = _AVAIL_END_RE.search(str(exc))
        if m:
            return _try(m.group(1))
        raise


def _download_sync(start: str, end: str) -> pd.DataFrame:
    """
    start/end are ET calendar dates (YYYY-MM-DD).
    Try the desired end; if Databento rejects it, parse the actual available
    end from the 422 error and retry.
    """
    client  = _client()
    end_str = _desired_end(end)

    def _try(e):
        return client.timeseries.get_range(
            dataset=DATASET, symbols=SYMBOLS, stype_in=STYPE,
            schema=SCHEMA, start=start, end=e,
        ).to_df()

    try:
        return _try(end_str)
    except Exception as exc:
        m = _AVAIL_END_RE.search(str(exc))
        if m:
            return _try(m.group(1))
        raise


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

        # Capture last date before we hand df off to the append worker
        ts_col = df.index if df.index.name == "ts_event" else df.get("ts_event")
        if ts_col is not None and len(ts_col) > 0:
            last = pd.Timestamp(ts_col.max())
            if last.tzinfo is None:
                last = last.tz_localize("UTC")
            new_end = last.tz_convert("UTC").strftime("%Y-%m-%d")
        else:
            new_end = end

        yield msg("progress", f"Downloaded {n_rows:,} rows. Appending to parquet...")
        new_rows = await loop.run_in_executor(_executor, _append_to_parquet, df)

        yield msg("progress", f"Added {new_rows:,} new rows. Rebuilding front-month cache (~30s)...")
        await loop.run_in_executor(_executor, _rebuild_cache)

        yield msg("done",
                  f"Done — {new_rows:,} new rows through {new_end}",
                  end_date=new_end)

    except Exception as e:
        yield msg("error", str(e))
