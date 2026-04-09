# Parquet read, timeframe aggregation, candle loading
import re
from calendar import FRIDAY
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

PARQUET_PATH      = Path(__file__).parent.parent / "data" / "es_1m.parquet"
FRONT_MONTH_PATH  = Path(__file__).parent.parent / "data" / "es_front_month.parquet"

OUTRIGHT_PATTERN  = re.compile(r"^ES[HMUZ]\d+$")

# ── Roll calendar ─────────────────────────────────────────────────────────────

_EXPIRY_MONTHS = [3, 6, 9, 12]
_MONTH_LETTER  = {3: "H", 6: "M", 9: "U", 12: "Z"}


def _third_friday(year: int, month: int) -> date:
    d = date(year, month, 1)
    days_to_fri = (FRIDAY - d.weekday()) % 7
    return d + timedelta(days=days_to_fri + 14)


def _is_edt(d: date) -> bool:
    y = d.year
    mar1      = date(y, 3, 1)
    dst_start = mar1 + timedelta(days=(6 - mar1.weekday()) % 7 + 7)
    nov1      = date(y, 11, 1)
    dst_end   = nov1 + timedelta(days=(6 - nov1.weekday()) % 7)
    return dst_start <= d < dst_end


def build_roll_calendar() -> list[tuple[pd.Timestamp, str]]:
    """
    Sorted list of (roll_utc_ts, symbol).
    Rule: roll at 18:00 ET on the Monday of ES expiry week
          (3rd Friday of expiry month − 4 days).
    Confirmed against TradingView for Sep-2025, Dec-2025, Mar-2026.
    """
    rolls = []
    for year in range(2015, 2028):
        for exp_month in _EXPIRY_MONTHS:
            friday = _third_friday(year, exp_month)
            monday = friday - timedelta(days=4)
            utc_hr = 22 if _is_edt(monday) else 23

            roll_dt = datetime(monday.year, monday.month, monday.day,
                               utc_hr, 0, 0, tzinfo=timezone.utc)

            if exp_month == 12:
                next_year, next_month = year + 1, 3
            else:
                idx = _EXPIRY_MONTHS.index(exp_month)
                next_year, next_month = year, _EXPIRY_MONTHS[idx + 1]

            symbol = f"ES{_MONTH_LETTER[next_month]}{next_year % 10}"
            rolls.append((pd.Timestamp(roll_dt), symbol))

    rolls.sort(key=lambda x: x[0])
    return rolls


# ── Pre-processed front-month Parquet ────────────────────────────────────────

def build_front_month_parquet() -> None:
    """
    Read es_1m.parquet, apply the roll calendar, write es_front_month.parquet.
    Adds an adj_offset column: additive back-adjustment offset for each bar so
    that adjusted = open/high/low/close + adj_offset.  Most recent segment = 0.
    Run once (or after importing new CSV data).  ~3.3M rows, ~25 MB on disk.
    """
    print("Building es_front_month.parquet …")
    df = pd.read_parquet(PARQUET_PATH)
    df = df[df["symbol"].str.match(OUTRIGHT_PATTERN)].copy()

    rolls    = build_roll_calendar()
    sentinel = pd.Timestamp("2030-01-01", tz="UTC")

    pieces = []
    for i, (roll_ts, symbol) in enumerate(rolls):
        next_ts = rolls[i + 1][0] if i + 1 < len(rolls) else sentinel
        mask = (
            (df["ts_event"] >= roll_ts) &
            (df["ts_event"] <  next_ts) &
            (df["symbol"]   == symbol)
        )
        pieces.append(df[mask])

    # ── Compute additive back-adjustment offsets ──────────────────────────────
    # At each roll boundary we need the contemporaneous spread: new contract
    # close MINUS old contract close at the same timestamp.
    #
    # We cannot use pieces[i].iloc[-1] for the old price because the CME
    # maintenance window (17:00–18:00 ET) creates a ~1-hour gap between the
    # last old-contract bar (≈16:59 ET) and the first new-contract bar (18:00
    # ET).  Market movement during that window inflates the apparent gap.
    #
    # Fix: at the roll boundary, look up the old contract in the raw df at the
    # same timestamp as the first new-contract bar.  Both contracts trade
    # simultaneously at 18:00 ET (Globex reopen), so we get a true spread.
    N = len(pieces)
    adj_offsets = [0.0] * N

    # Build a fast lookup: symbol → df subset (ts_event as index)
    df_indexed = df.set_index("ts_event").sort_index()

    for i in range(N - 2, -1, -1):
        if pieces[i].empty or pieces[i + 1].empty:
            adj_offsets[i] = adj_offsets[i + 1]
            continue

        first_new_ts    = pieces[i + 1]["ts_event"].iloc[0]
        first_new_price = float(pieces[i + 1]["close"].iloc[0])

        old_sym = rolls[i][1]   # symbol of segment i (becomes "old" at next roll)
        old_sym_df = df_indexed[df_indexed["symbol"] == old_sym]

        # Find the old contract's close at the same timestamp as the first new bar.
        # Fall back to the closest bar at or before that time if not exact.
        if first_new_ts in old_sym_df.index:
            old_price = float(old_sym_df.loc[first_new_ts, "close"])
            if isinstance(old_price, pd.Series):
                old_price = float(old_price.iloc[0])
        else:
            candidates = old_sym_df[old_sym_df.index <= first_new_ts]
            if candidates.empty:
                adj_offsets[i] = adj_offsets[i + 1]
                continue
            old_price = float(candidates["close"].iloc[-1])

        diff = first_new_price - old_price
        adj_offsets[i] = adj_offsets[i + 1] + diff

    for i in range(N):
        if not pieces[i].empty:
            pieces[i] = pieces[i].copy()
            pieces[i]["adj_offset"] = round(adj_offsets[i], 4)

    result = pd.concat(pieces).sort_values("ts_event").reset_index(drop=True)
    result.to_parquet(FRONT_MONTH_PATH, index=False)
    mb = FRONT_MONTH_PATH.stat().st_size / 1e6
    print(f"Done -- {len(result):,} rows, {mb:.1f} MB -> {FRONT_MONTH_PATH}")


# ── In-memory cache ───────────────────────────────────────────────────────────

_cache: pd.DataFrame | None = None


def warm_cache() -> None:
    """Load front-month data into memory.  Called at server startup."""
    global _cache
    if not FRONT_MONTH_PATH.exists():
        build_front_month_parquet()
    print("Loading es_front_month.parquet into memory …")
    df = pd.read_parquet(FRONT_MONTH_PATH)
    # Rebuild if adj_offset column is missing (parquet created before this feature)
    if "adj_offset" not in df.columns:
        print("adj_offset column missing — rebuilding front-month parquet …")
        build_front_month_parquet()
        df = pd.read_parquet(FRONT_MONTH_PATH)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True)
    df = df.set_index("ts_event").sort_index()
    _cache = df
    print(f"Cache ready — {len(_cache):,} rows")


def _get_cache() -> pd.DataFrame:
    global _cache
    if _cache is None:
        warm_cache()
    return _cache


# ── Public API ────────────────────────────────────────────────────────────────

def parse_timeframe(tf: str) -> int | None:
    if tf.upper() == "D":
        return None
    try:
        minutes = int(tf)
        if minutes < 1:
            raise ValueError
        return minutes
    except ValueError:
        raise ValueError(f"Invalid timeframe '{tf}'. Use a positive integer (minutes) or 'D'.")


def get_candles(
    timeframe: str = "5",
    start: str | None = None,
    end: str | None = None,
    adjusted: bool = False,
) -> list[dict]:
    """
    Return OHLCV candles. start/end are ET calendar dates.
    When adjusted=True, additive back-adjustment is applied so prices are
    continuous across roll dates (TradingView style).
    Served from in-memory cache — fast after first load.
    """
    df = _get_cache()

    # Slice by ET calendar date using the sorted index (O(log n) binary search)
    if start:
        start_ts = pd.Timestamp(start, tz="America/New_York").tz_convert("UTC")
        df = df.loc[start_ts:]
    if end:
        end_ts = (
            pd.Timestamp(end, tz="America/New_York")
            + pd.Timedelta(days=1)
            - pd.Timedelta(seconds=1)
        ).tz_convert("UTC")
        df = df.loc[:end_ts]

    if df.empty:
        return []

    minutes = parse_timeframe(timeframe)
    rule    = "D" if minutes is None else f"{minutes}min"

    # Apply back-adjustment offset to OHLC before resampling
    cols = ["open", "high", "low", "close", "volume"]
    if adjusted and "adj_offset" in df.columns:
        df = df[cols + ["adj_offset"]].copy()
        df["open"]  = df["open"]  + df["adj_offset"]
        df["high"]  = df["high"]  + df["adj_offset"]
        df["low"]   = df["low"]   + df["adj_offset"]
        df["close"] = df["close"] + df["adj_offset"]
        df_et = df[cols].copy()
    else:
        df_et = df[cols].copy()

    # Resample in ET so bar boundaries align with TradingView
    df_et.index = df_et.index.tz_convert("America/New_York")

    agg = (
        df_et.resample(rule)
        .agg(
            open=("open",    "first"),
            high=("high",    "max"),
            low =("low",     "min"),
            close=("close",  "last"),
            volume=("volume","sum"),
        )
        .dropna()
    )
    agg.index = agg.index.tz_convert("UTC")

    return [
        {
            "time":   int(ts.timestamp()),
            "open":   round(float(row["open"]),  2),
            "high":   round(float(row["high"]),  2),
            "low":    round(float(row["low"]),   2),
            "close":  round(float(row["close"]), 2),
            "volume": int(row["volume"]),
        }
        for ts, row in agg.iterrows()
    ]
