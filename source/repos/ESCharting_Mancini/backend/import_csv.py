"""One-time import: CSV → Parquet. Run from project root: python backend/import_csv.py"""
import sys
from pathlib import Path
import pandas as pd

CSV_PATH = Path(r"C:\Users\charl\Dropbox\Investing\Futures\Mancini FBDs\GLBX-20260329-F35ETXBBU3\glbx-mdp3-20160329-20260325.ohlcv-1m.csv")
PARQUET_PATH = Path(__file__).parent.parent / "data" / "es_1m.parquet"


def run():
    if not CSV_PATH.exists():
        print(f"ERROR: CSV not found at {CSV_PATH}", file=sys.stderr)
        sys.exit(1)

    print(f"Reading {CSV_PATH} ...")
    df = pd.read_csv(
        CSV_PATH,
        usecols=["ts_event", "open", "high", "low", "close", "volume", "symbol"],
    )

    # ts_event is ISO string with nanosecond precision — parse to UTC datetime
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True)

    df = df.sort_values("ts_event").reset_index(drop=True)

    print(f"Rows: {len(df):,}  |  Symbols: {sorted(df['symbol'].unique())}")
    print(f"Date range: {df['ts_event'].min()} to {df['ts_event'].max()}")

    PARQUET_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(PARQUET_PATH, index=False)
    print(f"Written: {PARQUET_PATH}")


if __name__ == "__main__":
    run()
