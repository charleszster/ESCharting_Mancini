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

## Feature summary
All core features are complete as of Apr 2026. Key capabilities:
- Candlestick chart with real ES 1-min data (2016–2026), multi-timeframe aggregation
- Trade list (left panel) + detail (right panel), markers on chart, clicking a trade zooms chart
- **Batch view** (top of left panel): show all trades in a date range simultaneously; filter by All / Winners / Losers (unlit until selected, clear to unlit on Clear); "Show on chart" is neutral until active, then turns blue; chart auto-spans first entry −28 days to last exit +28 days; clicking a trade exits batch mode and zooms to it
- Manual and auto support/resistance levels, both editable/toggleable
- Adjusted/non-adjusted price mode toggle (additive back-adjustment, TV-compatible)
- Databento data download (SSE streaming, retry loop for 422s, precise start timestamp to avoid redundant rows) and TradingView CSV import
- ETH/RTH session shading, full chart settings modal (7 tabs), crosshair modes
- Reset view button (⊡): pins latest bar at 120px from right, shows 270 bars (constant RESET_BARS in Chart.jsx)
- start.bat launches both backend and frontend; browser opens at localhost:5173

## Roll calendar rule
- Roll at 18:00 ET on the Monday of the expiry week (= 3rd Friday of expiry month − 4 days)
- Confirmed against TradingView export for Sep-2025, Dec-2025, Mar-2026 rolls
- In UTC: 22:00 UTC during EDT (Mar–Nov), 23:00 UTC during EST (Nov–Mar)
- After fix: max 10pt diff vs TV (was ±51pt), 8 bars in 3264 differ slightly (feed noise)

## What's next
- Step 10: Auto level ML classifier (Phase 6) — **integration complete**; two UI/algo improvements queued
  - Phase 6e model (phase6e_model.json) is wired into auto_levels.py; each level carries a `score` field
  - `major` is now determined by ML score ≥ 0.5 (was bounce/touches heuristic)
  - **4/13/2026 comparison vs Mancini's published levels:**
    - Supports (in range): 41/42 matched ±2pt (98%). Miss only 1. 31 extras, but model is confident in most.
    - Resistances (in range): 24/36 matched ±2pt (67%). Miss 12 levels in 7048–7139 ATH zone.
    - ATH resistance gap is structural: market ran up there briefly, no clean pivot formations for algo to find.
  - **Next two tasks (in priority order):**
    1. **Score filter UI** — add `min_score` parameter (default 0.0, e.g. 0.35 removes low-conf extras without losing Mancini matches) as a setting in the Auto Levels tab; pass through backend API; filter before returning levels
    2. **ATH cluster detection** — after standard dedup, scan for top-N highest pivot highs in lookback window not already covered by an accepted level (within 5pt); adds the "ATH resistance cluster" that pivot geometry misses near the top of the prior move
  - See docs/auto_level_study.md for full methodology and results

## Auto level generation methodology
Derived from Mancini Pine Script v5.3, adapted and corrected. Implemented in `backend/auto_levels.py`.

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
- Price must be within ±325 pts of `close4pm` (configurable)
- Pivots processed newest-first (reverse chronological) — most recent test of a price zone wins
- Deduplication: if new candidate is within `minSpacing` pts (default 3.0) of any already-accepted level, skip it

### Bounce measurement (strength signal)
- Bounce follows the **pivot type**, not the support/resistance classification:
  - Pivot high at price P, time T: find min pivot low in (T, T + N_forward bars] → `bounce = P − min_low`
  - Pivot low at price P, time T: find max pivot high in same window → `bounce = max_high − P`
- This measures how strongly price was historically rejected from the level, regardless of its current role
- A pivot low above close4pm (acting as resistance) still measures bounce as max_high_after − P
- Default N_forward = 10 bars (= 2.5 hrs on 15-min) — tuned in Phase 5 (was 100)

### Touch counting (confluence signal)
- Count all pivot highs AND pivot lows (timestamp ≤ 4pm anchor) within ±`touchZone` pts (default 2.0) of P
- Forward touches (after 4pm) are excluded — avoids future data leakage

### Major vs. minor classification
- `isMajor = bounce ≥ majBounce (default 40 pts)  OR  touches ≥ majTouches (default 12)`
- Minor = everything else (drawn as dashed line)
- Defaults tuned via 5-phase parameter study (see docs/auto_level_study.md) to match Mancini's ~42% major ratio

### Configurable parameters (new Settings tab)
| Parameter | Default | Notes |
|---|---|---|
| Pivot lookback (bars/side) | 5 | integer |
| Price range (±pts) | 325 | float — tuned in Phase 2 (was 250) |
| Min level spacing (pts) | 3.0 | float |
| Touch zone (±pts) | 2.0 | float |
| Major bounce threshold (pts) | 40 | float |
| Major touch threshold | 12 | integer — tuned in Phase 5 (was 5) |
| Bounce forward window (bars) | 10 | integer — tuned in Phase 5 (was 100) |
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
- Databento pipeline lag: subscription tier has ~13hr lag (data available up to ~10:54am ET when downloaded at 7pm ET); two successive 422s occur: first "data_end_after_available_end" (pipeline limit), then "dataset_unavailable_range" (subscription cap); downloader loops up to 4 times backing off 1 min each time
- TradingView CSV export: MES1! or ES1!, 1-min, columns: time/open/high/low/close (no volume); timestamps in ISO-8601 with UTC offset; use as same-day stopgap after 4pm close; TV shows volume in the table view and claims to export all data, but volume column is absent from the downloaded CSV — volume=0 is set on import (irrelevant for auto levels and chart display)
- Download modal "From" field: read-only, auto-set to the exact UTC timestamp of the last bar in the parquet (from /candles/bounds end_ts). This is sent verbatim to Databento so only truly new bars are fetched. Previously used nextDay(dataEnd) which rounded to UTC midnight and could cause hours of overlap; also had a race condition where the modal could initialize before /candles/bounds resolved, defaulting to 2026-03-25.
- Download modal "Done" message shows exact ET timestamp of last downloaded bar (e.g. "Done — data through 4/10/2026, 3:08 PM ET"), not just the date.
- databento Python package: v0.74.1 installed in venv
- start.bat corruption: `venv\Scripts\activate` was corrupted to `vnot bpts\activate` at some point — if backend fails to start, check start.bat

## User preferences
- Visual-first: always keep the app in a runnable state
- Never break working features to add new ones
- Ask before making architectural changes
- Keep CLAUDE.md up to date at the end of every session
