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
- Columns: ts_event, rtype, publisher_id, instrument_id, open, high, low, close, volume, symbol
- Prices are already in dollar format — NO scaling needed (CLAUDE.md previously said divide by 1e9, that was wrong)

## Trade log
- Path: C:\Users\charl\Dropbox\Investing\Futures\Trades - MES.xlsm
- Sheet: Consolidated Mancini FBD Trades
- Configured via .env: TRADES_FILE and TRADES_SHEET variables
- 70 trades as of Apr 2026, date range 2025-10-29 to 2026-03-30
- Columns: Entry Date/Time/Qty/Price, Exit 1–N Date/Time/Qty/Price (dynamic, any number), Total Commission, Net P/L
- Entry Qty > 0 = long, < 0 = short
- File is NEVER written to — read-only openpyxl

## User info
- Location: US Eastern Time
- Databento API key: stored in .env (user fills in manually)

## Current state
- [x] Project scaffolded
- [x] Chart visible with hardcoded data — full UI shell complete
- [x] Real Parquet data loading (es_1m.parquet, 5.5M rows, 2016–2026)
- [x] GET /candles endpoint with timeframe aggregation
- [x] Chart fetches real ES data, loading overlay while fetching
- [x] Timeframe selector buttons wired to re-fetch
- [x] TV roll calendar (Monday of expiry week at 18:00 ET) — max 10pt diff vs TV
- [x] ET timezone display on chart axis and crosshair
- [x] Date range picker treats dates as ET midnight
- [x] OHLCV hover tooltip (absolute positioned, top-left of chart)
- [x] ETH/RTH session shading (configurable color, opacity, mode)
- [x] Full chart settings modal (6 tabs: Candles, Grid, Sessions, Volume, Scales, Crosshair)
- [x] TV-style UI (dark border palette, accent colors, toggle switches)
- [x] Performance: pre-processed es_front_month.parquet + in-memory RAM cache
- [x] Reset view button in toolbar (fitContent + auto-scale price axis)
- [x] GET /trades endpoint — reads Excel read-only via openpyxl
- [x] Trade list in left panel: date, L/S, P/L, entry→exit times, contract count (2-line rows)
- [x] Clicking a trade loads ±6 months of data and zooms chart to 7 days before / 3 days after trade date
- [x] Left and right panels resizable by dragging border
- [x] Both panels collapsible (left: bottom toggle, right: bottom toggle)
- [x] Trade log path/sheet configured via .env (TRADES_FILE, TRADES_SHEET)
- [x] Trade markers on chart — custom LWC v5 primitive (TradeMarkersPrimitive), arrows pinned to exact entry/exit price, white halo + label background for visibility
- [x] Marker label font size configurable (⚙ Markers tab, default 11px, range 8–20px)
- [x] Crosshair modes: Snap to close (default), Snap to OHLC (custom price line), Free, Hidden
- [x] Trade detail in right panel — entry/exit rows, gross/commission/net P&L, duration, multi-exit + cross-day support; "Planning Mode" placeholder when no trade selected
- [x] Adjusted/non-adjusted toggle — adj_offset computed at roll boundaries in es_front_month.parquet using contemporaneous spreads (both contracts at same timestamp); Adj button re-fetches with ?adjusted=true; Non-Adj is default; status bar shows current mode; validated against TV MES1! daily closes (MAD ~1.2 pts, within-period drift ~0)
- [x] Level lines on chart — green supports / red resistances, solid=major / dashed=minor, label on chart at right edge, one date at a time
- [x] Levels sourced from data/levels.db (SQLite, imported once from Excel via import_levels.py, 221 rows 2025-03-07 to 2026-04-06)
- [x] Default levels capped at DATA_END (2026-03-25) so no phantom future levels show
- [x] Trade click auto-loads levels for that trade date AND forces non-adjusted mode
- [x] Reset button restores latest levels (capped at DATA_END)
- [x] Levels date picker in right panel; "latest" button resets to DATA_END; matched date shown below picker and in status bar
- [x] Levels editable via right-panel textareas (raw string format); Save button PUTs to /levels and updates chart immediately
- [x] "Save to date" input lets user change the target date — handles both editing existing entries and adding new ones; view switches to saved date after save
- [x] Levels visible toggle in Layers section — hides/shows all level lines without losing date selection
- [x] "Re-import from Excel" button calls POST /levels/reimport — re-reads the Excel file and upserts all rows; shows count + latest date on completion
- [ ] Auto level generation (30-min bars, Mancini Pine Script logic)
- [ ] Databento download modal

## Roll calendar rule
- Roll at 18:00 ET on the Monday of the expiry week (= 3rd Friday of expiry month − 4 days)
- Confirmed against TradingView export for Sep-2025, Dec-2025, Mar-2026 rolls
- In UTC: 22:00 UTC during EDT (Mar–Nov), 23:00 UTC during EST (Nov–Mar)
- After fix: max 10pt diff vs TV (was ±51pt), 8 bars in 3264 differ slightly (feed noise)

## What's next
- Step 8: (done — add/edit/toggle/reimport all complete)
- Step 9: Auto level generation (Mancini Pine Script logic on 30-min bars)
- Step 10: Databento download modal

## Active bug (as of 2026-04-09)
- **Textareas not clearing when picking a date not in the DB** (e.g. 4/7/2026)
  - When user picks a new date in the Levels date picker, the resistance/support textareas should go blank (to signal "new entry"), but they still show the previous date's data
  - Two fix attempts failed; a `console.log` was added to the useEffect in `LevelsPanel.jsx` to diagnose
  - Need to open browser DevTools (F12 → Console), pick 4/7/2026, and report what `[LevelsPanel effect]` logs show for `levelsDate`, `levelsData.date`, and `exactMatch`
  - The fix attempts are in the current useEffect and onChange handler in `LevelsPanel.jsx`

## Known issues / gotchas
- CSV column is `volume` (no typo)
- Databento prices are already in dollar format — no scaling needed
- On Windows, if Excel has the trade log open with an exclusive lock, pandas read will fail — user should close Excel first
- python-dotenv is installed in the venv and used by trades_manager.py
- Python command on this system: `python` (3.12.11)
- First backend start after adding es_front_month.parquet builds the file (~30s), subsequent starts load from RAM in ~1s
- es_1m.parquet: 73MB raw source (DO NOT DELETE); es_front_month.parquet: ~25MB preprocessed (can be rebuilt)
- Data bounds: 2016-03-29 to 2026-03-25 (hardcoded as DATA_START/DATA_END in App.jsx for trade navigation clamping)

## User preferences
- Visual-first: always keep the app in a runnable state
- Never break working features to add new ones
- Ask before making architectural changes
- Keep CLAUDE.md up to date at the end of every session
