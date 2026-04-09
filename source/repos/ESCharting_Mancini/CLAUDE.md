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
- Auto levels always computed on 15-minute bars, anchored to most recent 4pm ET close
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
- [x] Default levels — GET /levels with no date param returns most recent DB entry (no DATA_END cap needed)
- [x] Trade click auto-loads levels for that trade date AND forces non-adjusted mode
- [x] Reset button restores latest levels (most recent DB entry)
- [x] Levels date picker in right panel; "latest" button resets to most recent DB entry; matched date shown below picker and in status bar
- [x] Levels editable via right-panel textareas (raw string format); Save button PUTs to /levels and updates chart immediately
- [x] "Save to date" input lets user change the target date — handles both editing existing entries and adding new ones; view switches to saved date after save
- [x] Levels visible — manual and auto toggles in Layers section (no master toggle); chart receives merged result
- [x] "Re-import from Excel" button calls POST /levels/reimport — re-reads the Excel file and upserts all rows; shows count + latest date on completion
- [x] Databento download modal — "Download data" button in topbar opens modal; cost estimate + confirm step; SSE streaming progress; appends to es_1m.parquet (dedup), rebuilds es_front_month.parquet, updates dataEnd in App state; backend: downloader.py + /download/estimate + /download/stream endpoints; chart dateRange.end updates automatically on success
- [x] Databento download end-date handling — adds 1 day to make end inclusive; uses try/retry approach: attempt desired end, if Databento 422s with "available up to 'TIMESTAMP'", parse that timestamp and retry; get_dataset_range() removed (returned stale/conservative end, got data only to 9am ET when 4pm ET was actually available)
- [x] ETH shading fix — SessionHighlight.js now clamps band endpoints to chart edges instead of dropping the band when timeToCoordinate returns null (was cutting off overnight shading at last data bar)
- [x] start.bat at project root — double-click launches backend + frontend; browser auto-opens at localhost:5173 via Vite server.open
- [x] Default chart date range — fetched from GET /candles/bounds on mount (reads actual parquet min/max); shows 6 months before actual data end; no longer hardcoded
- [x] Default crosshair mode — Snap to OHLC (mode 3); was Snap to close (mode 1)
- [x] Level labels on chart — LevelLabelsPrimitive (custom LWC v5 canvas primitive); colored text at right edge, no background box by default; font size 9px default
- [x] Range levels drawn as zones — price_lo/price_hi returned from backend; two boundary lines drawn (at lo and hi, not midpoint); translucent fill between them (10% opacity default); backend _parse_token handles 4+2-digit shorthand (e.g. 6766-70 → 6766/6770)
- [x] Level label/zone settings in ⚙ Markers tab — font size slider, color box toggle, show zones toggle, zone opacity slider
- [x] Auto level generation — GET /levels/auto; backend: auto_levels.py (15-min bars, numpy vectorised pivots, bounce/touch/major logic); "Generate auto levels" button + date picker in right panel; auto levels displayed in read-only collapsible section; manual and auto levels each have independent on/off toggles; all params configurable in ⚙ Auto Levels tab
- [x] Auto levels date picker — date = the day levels are FOR (prior trading day's 4pm is the anchor); Monday picks Friday's 4pm automatically
- [x] Manual levels default date — now calls GET /levels with no date param on mount, returning most recent DB entry instead of stale hardcoded DATA_END
- [x] ETH shading fix (Sunday gap) — SessionHighlight.js rewritten to shade gaps *between* RTH windows rather than UTC calendar days; fixes 6–8 PM ET Sunday showing as unshaded because UTC-midnight timestamps in trading gaps return null from timeToCoordinate
- [x] start.bat — 2-window approach: backend in separate cmd window, frontend in bat window; Ctrl+C kills frontend then auto-kills backend

## Roll calendar rule
- Roll at 18:00 ET on the Monday of the expiry week (= 3rd Friday of expiry month − 4 days)
- Confirmed against TradingView export for Sep-2025, Dec-2025, Mar-2026 rolls
- In UTC: 22:00 UTC during EDT (Mar–Nov), 23:00 UTC during EST (Nov–Mar)
- After fix: max 10pt diff vs TV (was ±51pt), 8 bars in 3264 differ slightly (feed noise)

## What's next
- Step 10: Analyze and tune auto level parameters vs Mancini's published levels (ongoing experiment)

## Auto level generation methodology
Derived from Mancini Pine Script v5.3, adapted and corrected. Not yet implemented in Python.

### Anchor
- Aggregate 1-min parquet data into 15-min bars
- Find the most recent 15-min bar whose close time = 4:00 PM ET (bar opens 3:45 PM, closes 4:00 PM)
- `close4pm` = close price of that bar; this is the price reference for all classification

### Pivot detection
- Confirm pivot highs and lows using N bars on each side (default N=5, configurable)
- A pivot high at bar i: `high[i] > high[i-k]` and `high[i] > high[i+k]` for all k in [1..N]
- A pivot low at bar i: symmetric
- Only pivots with timestamp ≤ 4pm anchor bar are considered (no future data leakage)

### Level classification (corrected from Pine Script)
- Pine Script always maps pivot highs → resistance and pivot lows → support
- Correct behavior: classification is by price location relative to `close4pm`, not pivot type
  - Pivot (high or low) with price > `close4pm` → **resistance**
  - Pivot (high or low) with price < `close4pm` → **support**
  - This captures "prior support acting as resistance" and vice versa

### Candidate filtering
- Price must be within ±250 pts of `close4pm` (configurable)
- Pivots processed newest-first (reverse chronological) — most recent test of a price zone wins
- Deduplication: if new candidate is within `minSpacing` pts (default 3.0) of any already-accepted level, skip it

### Bounce measurement (strength signal)
- Bounce follows the **pivot type**, not the support/resistance classification:
  - Pivot high at price P, time T: find min pivot low in (T, T + N_forward bars] → `bounce = P − min_low`
  - Pivot low at price P, time T: find max pivot high in same window → `bounce = max_high − P`
- This measures how strongly price was historically rejected from the level, regardless of its current role
- A pivot low above close4pm (acting as resistance) still measures bounce as max_high_after − P
- Default N_forward = 100 bars (= 25 hrs on 15-min)

### Touch counting (confluence signal)
- Count all pivot highs AND pivot lows (timestamp ≤ 4pm anchor) within ±`touchZone` pts (default 2.0) of P
- Forward touches (after 4pm) are excluded — avoids future data leakage

### Major vs. minor classification
- `isMajor = bounce ≥ majBounce (default 40 pts)  OR  touches ≥ majTouches (default 5)`
- Minor = everything else (drawn as dashed line)

### Configurable parameters (new Settings tab)
| Parameter | Default | Notes |
|---|---|---|
| Pivot lookback (bars/side) | 5 | integer |
| Price range (±pts) | 250 | float |
| Min level spacing (pts) | 3.0 | float |
| Touch zone (±pts) | 2.0 | float |
| Major bounce threshold (pts) | 40 | float |
| Major touch threshold | 5 | integer |
| Bounce forward window (bars) | 100 | integer |
| Show major only | false | toggle |
| Show supports | true | toggle |
| Show resistances | true | toggle |

### Storage and UI
- Auto levels are NOT saved to levels.db — computed in memory only, displayed in read-only collapsible section
- Date picker represents the day levels are FOR (anchor = prior trading day's 4pm); blank = most recent 4pm in parquet
- Auto levels do NOT update when user clicks a trade (manual levels do) — auto levels stay pinned to selected date
- Manual and auto levels each have an independent on/off toggle in the right panel (no master toggle)
- Displayed on chart alongside manual levels, same visual style (green/red, solid/dashed)
- "Auto Levels" tab in ⚙ settings modal exposes all parameters; "Copy to editor" removed — use read-only section to copy text
- supports_raw / resistances_raw returned by backend (sorted: resistances ascending, supports descending)


## Known issues / gotchas
- CSV column is `volume` (no typo)
- Databento prices are already in dollar format — no scaling needed
- On Windows, if Excel has the trade log open with an exclusive lock, pandas read will fail — user should close Excel first
- python-dotenv is installed in the venv and used by trades_manager.py
- Python command on this system: `python` (3.12.11)
- First backend start after adding es_front_month.parquet builds the file (~30s), subsequent starts load from RAM in ~1s
- es_1m.parquet: 73MB raw source (DO NOT DELETE); es_front_month.parquet: ~25MB preprocessed (can be rebuilt)
- Data bounds: DATA_START='2016-03-29' is a const in App.jsx; DATA_END is now useState('2026-03-25') so it updates after a successful download
- Databento pipeline lag: ~8hr observed on overnight data; get_dataset_range() returns conservative/stale available end — downloader now uses try/retry with 422 error message parsing instead (actual available end is accurate)
- databento Python package: v0.74.1 installed in venv
- start.bat corruption: `venv\Scripts\activate` was corrupted to `vnot bpts\activate` at some point — if backend fails to start, check start.bat

## User preferences
- Visual-first: always keep the app in a runnable state
- Never break working features to add new ones
- Ask before making architectural changes
- Keep CLAUDE.md up to date at the end of every session
