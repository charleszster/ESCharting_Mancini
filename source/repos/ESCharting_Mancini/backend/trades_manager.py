"""
Read-only access to the Excel trade log.
The file is NEVER written to — only opened with openpyxl in read-only mode.
"""
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

TRADES_PATH = Path(os.environ["TRADES_FILE"])
SHEET_NAME  = os.environ["TRADES_SHEET"]


def _fmt_time(val) -> str | None:
    """Convert whatever pandas gives us for a time cell to HH:MM:SS."""
    if pd.isna(val):
        return None
    # pandas may return datetime.time, Timestamp, or timedelta
    if hasattr(val, 'strftime'):
        return val.strftime('%H:%M:%S')
    if hasattr(val, 'components'):          # timedelta
        h, m, s = int(val.components.hours), int(val.components.minutes), int(val.components.seconds)
        return f"{h:02d}:{m:02d}:{s:02d}"
    return str(val)


def get_trades() -> list[dict]:
    """
    Return all trades sorted newest-first.
    Detects exit columns dynamically — handles any number of exits.
    Raises FileNotFoundError if the Excel file is missing.
    """
    if not TRADES_PATH.exists():
        raise FileNotFoundError(f"Trade log not found: {TRADES_PATH}")

    df = pd.read_excel(
        TRADES_PATH,
        sheet_name=SHEET_NAME,
        engine="openpyxl",
    )
    df = df.dropna(subset=["Entry Date"])

    # Detect how many exits exist by scanning column headers
    import re
    exit_numbers = sorted({
        int(m.group(1))
        for col in df.columns
        if (m := re.match(r"^Exit (\d+) Date$", str(col)))
    })

    trades = []
    for idx, row in df.iterrows():
        entry_date = pd.Timestamp(row["Entry Date"])
        direction = "long" if float(row["Entry Qty"]) > 0 else "short"

        exits = []
        for n in exit_numbers:
            if pd.notna(row.get(f"Exit {n} Date")):
                exits.append({
                    "date":  pd.Timestamp(row[f"Exit {n} Date"]).strftime("%Y-%m-%d"),
                    "time":  _fmt_time(row.get(f"Exit {n} Time")),
                    "qty":   int(row[f"Exit {n} Qty"]),
                    "price": round(float(row[f"Exit {n} Price"]), 2),
                })

        trades.append({
            "id":          int(idx),
            "entry_date":  entry_date.strftime("%Y-%m-%d"),
            "entry_time":  _fmt_time(row.get("Entry Time")),
            "entry_qty":   int(row["Entry Qty"]),
            "entry_price": round(float(row["Entry Price"]), 2),
            "direction":   direction,
            "exits":       exits,
            "commission":  round(float(row["Total Commission"]), 2) if pd.notna(row.get("Total Commission")) else 0.0,
            "net_pnl":     round(float(row["Net P/L"]), 2) if pd.notna(row.get("Net P/L")) else 0.0,
        })

    trades.sort(key=lambda t: (t["entry_date"], t["entry_time"] or ""), reverse=True)
    return trades
