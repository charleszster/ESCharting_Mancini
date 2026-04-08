# ES Trade Analyzer — Project Memory

## What this is
A local desktop web app for analyzing ES futures trades on a candlestick chart.
Python (FastAPI) backend + React (Vite) + TradingView Lightweight Charts frontend.
Single user, Windows, 1080p, light theme.

## Key decisions
- ES price data stored as Parquet locally, sourced from Databento (GLBX.MDP3, ohlcv-1m)
- Trade log lives in Excel (read-only from app — user edits directly in Excel)
- Levels (manual + auto) stored in SQLite (levels.db)
- Two data modes: Adjusted (back-adjusted, for planning) and Non-Adjusted (for trade review)
- Non-adjusted is the default when reviewing trades
- Auto levels always computed on 30-minute bars, replicating Mancini Pine Script logic
- Roll methodology replicates TradingView: quarterly CME roll, additive back-adjustment
- Globex and RTH sessions treated identically — no session filtering
- Project root: C:\Users\charl\source\repos\ESCharting_Mancini
- GitHub repo: charleszster/ESCharting_Mancini

## CSV source data
- Path: C:\Users\charl\Dropbox\Investing\Futures\Mancini FBDs\GLBX-20260329-F35ETXBBU3\glbx-mdp3-20160329-20260325.ohlcv-1m.csv
- Columns: ts_event, rtype, publisher_id, instrument_id, open, high, low, close, volumne (typo in source), symbol
- Price columns (open/high/low/close) are in fixed-point format from Databento — divide by 1e9 to get dollar prices

## User info
- Location: US Eastern Time
- Trade log: Excel file (path to be configured in Settings panel)
- Databento API key: stored in .env (user fills in manually)

## Current state
- [x] Project scaffolded
- [x] Chart visible with hardcoded data — full UI shell complete
- [ ] Real Parquet data loading
- [ ] Timeframe aggregation working
- [ ] Trade list from Excel
- [ ] Trade markers on chart
- [ ] Level lines on chart
- [ ] Right panel wired up
- [ ] Adjusted/non-adjusted toggle
- [ ] Auto level generation
- [ ] Databento download modal
- [ ] Roll calculation complete

## What's next
- Step 3: CSV → Parquet conversion (one-time import), backend GET /candles endpoint,
  chart loads real ES data for a default date, loading state while fetching
- Step 4 follows immediately after: wire up timeframe selector buttons

## Known issues / gotchas
- CSV column "volumne" is a typo in the source file — match it exactly during import
- Databento prices are fixed-point integers: divide by 1,000,000,000 to get dollar prices
- On Windows, if Excel has the trade log open with an exclusive lock, pandas read will fail — user should close Excel first
- Python command on this system: `python` (3.12.11)

## User preferences
- Visual-first: always keep the app in a runnable state
- Never break working features to add new ones
- Ask before making architectural changes
- Keep CLAUDE.md up to date at the end of every session
