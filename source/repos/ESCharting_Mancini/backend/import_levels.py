"""
One-time import: reads trade_plans_running_list.xlsm and writes every row
into data/levels.db (SQLite).  Safe to re-run — uses INSERT OR REPLACE.
"""
import os
import sqlite3
import sys
from pathlib import Path

import openpyxl
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

LEVELS_FILE = Path(os.getenv(
    "LEVELS_FILE",
    r"C:\Users\charl\Dropbox\Investing\Futures\Mancini FBDs\mes_levels_project\output\trade_plans_running_list.xlsm",
))
LEVELS_DB = Path(__file__).parent.parent / "data" / "levels.db"


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS levels (
            trading_date  TEXT PRIMARY KEY,
            supports      TEXT NOT NULL DEFAULT '',
            resistances   TEXT NOT NULL DEFAULT '',
            source        TEXT DEFAULT 'import'
        )
    """)
    conn.commit()


def run() -> None:
    if not LEVELS_FILE.exists():
        sys.exit(f"ERROR: levels file not found: {LEVELS_FILE}")

    print(f"Reading {LEVELS_FILE} ...")
    wb = openpyxl.load_workbook(LEVELS_FILE, read_only=True, data_only=True)
    ws = wb.active

    conn = sqlite3.connect(LEVELS_DB)
    init_db(conn)

    count = 0
    for row in ws.iter_rows(values_only=True):
        if row[0] == "trading_date" or row[0] is None:
            continue
        raw_date = row[0]
        d = raw_date.date() if hasattr(raw_date, "date") else raw_date
        conn.execute(
            "INSERT OR REPLACE INTO levels (trading_date, supports, resistances, source) "
            "VALUES (?, ?, ?, 'import')",
            (str(d), row[1] or "", row[2] or ""),
        )
        count += 1

    conn.commit()
    conn.close()
    print(f"Done -- {count} rows -> {LEVELS_DB}")


if __name__ == "__main__":
    run()
