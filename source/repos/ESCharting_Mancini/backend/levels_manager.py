# Reads and writes Mancini support/resistance levels from data/levels.db (SQLite).
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path

import openpyxl
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

LEVELS_FILE = Path(os.getenv(
    "LEVELS_FILE",
    r"C:\Users\charl\Dropbox\Investing\Futures\Mancini FBDs\mes_levels_project\output\trade_plans_running_list.xlsm",
))

LEVELS_DB = Path(__file__).parent.parent / "data" / "levels.db"


# ── Level string parsing ──────────────────────────────────────────────────────

def _parse_token(token: str) -> dict | None:
    """
    Parse one comma-separated level token, e.g.:
      "6500"            -> {price: 6500.0, major: False, label: "6500"}
      "6500 (major)"    -> {price: 6500.0, major: True,  label: "6500"}
      "6525-30 (major)" -> {price: 6527.5, major: True,  label: "6525-30"}
      "5495-5500"       -> {price: 5497.5, major: False, label: "5495-5500"}
    """
    token = token.strip()
    if not token:
        return None

    major = bool(re.search(r"\(major\)", token, re.IGNORECASE))
    clean = re.sub(r"\s*\(major\)\s*", "", token, flags=re.IGNORECASE).strip()

    # Range: two numbers joined by a dash (not a leading minus sign)
    range_match = re.match(r"^(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)$", clean)
    if range_match:
        p1 = float(range_match.group(1))
        p2_str = range_match.group(2)
        p1_int_len = len(str(int(p1)))
        if len(p2_str.replace(".", "")) < p1_int_len:
            n = len(p2_str)
            p2 = float(str(int(p1))[:-n] + p2_str)
        else:
            p2 = float(p2_str)
        price = round((p1 + p2) / 2, 2)
        return {"price": price, "major": major, "label": clean}

    try:
        price = float(clean)
        return {"price": price, "major": major, "label": clean}
    except ValueError:
        return None


def _parse_levels_str(s: str) -> list[dict]:
    if not s:
        return []
    return [p for tok in s.split(",") if (p := _parse_token(tok)) is not None]


# ── SQLite helpers ────────────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(LEVELS_DB)
    c.row_factory = sqlite3.Row
    return c


def _row_to_response(row) -> dict:
    if row is None:
        return {"date": None, "supports": [], "resistances": [],
                "supports_raw": "", "resistances_raw": ""}
    return {
        "date":            row["trading_date"],
        "supports":        _parse_levels_str(row["supports"]),
        "resistances":     _parse_levels_str(row["resistances"]),
        "supports_raw":    row["supports"],
        "resistances_raw": row["resistances"],
    }


# ── Public API ────────────────────────────────────────────────────────────────

def get_available_dates() -> list[str]:
    """All trading_date values as ISO strings, most-recent-first."""
    with _conn() as c:
        rows = c.execute(
            "SELECT trading_date FROM levels ORDER BY trading_date DESC"
        ).fetchall()
    return [r["trading_date"] for r in rows]


def get_levels(date_str: str | None = None) -> dict:
    """
    Return levels for the nearest trading_date on or before date_str.
    If date_str is None, returns the most recent row.
    Includes raw strings (supports_raw / resistances_raw) for the edit UI.
    """
    with _conn() as c:
        if date_str is None:
            row = c.execute(
                "SELECT * FROM levels ORDER BY trading_date DESC LIMIT 1"
            ).fetchone()
        else:
            row = c.execute(
                "SELECT * FROM levels WHERE trading_date <= ? "
                "ORDER BY trading_date DESC LIMIT 1",
                (date_str,),
            ).fetchone()
    return _row_to_response(row)


def reimport_from_excel() -> dict:
    """
    Re-read the Excel file and upsert every row into levels.db.
    Safe to call repeatedly — uses INSERT OR REPLACE.
    Returns {"imported": N, "latest_date": "YYYY-MM-DD"}.
    """
    if not LEVELS_FILE.exists():
        raise FileNotFoundError(f"Levels file not found: {LEVELS_FILE}")

    wb = openpyxl.load_workbook(LEVELS_FILE, read_only=True, data_only=True)
    ws = wb.active

    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS levels (
                trading_date  TEXT PRIMARY KEY,
                supports      TEXT NOT NULL DEFAULT '',
                resistances   TEXT NOT NULL DEFAULT '',
                source        TEXT DEFAULT 'import'
            )
        """)
        count = 0
        latest = None
        for row in ws.iter_rows(values_only=True):
            if row[0] == "trading_date" or row[0] is None:
                continue
            raw_date = row[0]
            d = str(raw_date.date() if hasattr(raw_date, "date") else raw_date)
            c.execute(
                "INSERT OR REPLACE INTO levels "
                "(trading_date, supports, resistances, source) VALUES (?, ?, ?, 'import')",
                (d, row[1] or "", row[2] or ""),
            )
            count += 1
            if latest is None or d > latest:
                latest = d

    return {"imported": count, "latest_date": latest}


def save_levels(date_str: str, supports_raw: str, resistances_raw: str) -> dict:
    """
    Upsert levels for the exact trading_date given.
    Returns the updated row as a response dict.
    """
    with _conn() as c:
        c.execute(
            "INSERT INTO levels (trading_date, supports, resistances, source) "
            "VALUES (?, ?, ?, 'edit') "
            "ON CONFLICT(trading_date) DO UPDATE SET "
            "  supports=excluded.supports, "
            "  resistances=excluded.resistances, "
            "  source='edit'",
            (date_str, supports_raw, resistances_raw),
        )
        row = c.execute(
            "SELECT * FROM levels WHERE trading_date = ?", (date_str,)
        ).fetchone()
    return _row_to_response(row)
