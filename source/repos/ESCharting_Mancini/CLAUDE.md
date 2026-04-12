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
- Prices are already in dollar format — NO scaling needed

## Trade log
- Path: C:\Users\charl\Dropbox\Investing\Futures\Trades - MES.xlsm
- Sheet: Consolidated Mancini FBD Trades
- Configured via .env: TRADES_FILE and TRADES_SHEET variables
- ~70 trades as of Apr 2026, date range 2025-10-29 to 2026-03-30
- Columns: Entry Date/Time/Qty/Price, Exit 1–N Date/Time/Qty/Price (dynamic), Total Commission, Net P/L
- Entry Qty > 0 = long, < 0 = short
- File is NEVER written to — read-only openpyxl

## User info
- Location: US Eastern Time
- Databento API key: stored in .env (user fills in manually)

## Feature summary
All core features are complete. Key capabilities:
- Candlestick chart with real ES 1-min data (2016–2026), multi-timeframe aggregation
- Trade list (left panel) + detail (right panel), markers on chart, clicking a trade zooms chart
- **Batch view**: show all trades in a date range simultaneously; filter by All/Winners/Losers; "Show on chart" turns blue when active; chart auto-spans first entry −28 days to last exit +28 days; clicking a trade exits batch mode and zooms to it
- Manual and auto support/resistance levels, both editable/toggleable
- Adjusted/non-adjusted price mode toggle (additive back-adjustment, TV-compatible)
- Databento data download (SSE streaming, retry loop for 422s, precise start timestamp) and TradingView CSV import
- ETH/RTH session shading, full chart settings modal (8 tabs), crosshair modes
- Reset view button (⊡): pins latest bar at 120px from right, shows 270 bars (RESET_BARS in Chart.jsx)
- start.bat launches both backend and frontend; browser opens at localhost:5173

## Roll calendar rule
- Roll at 18:00 ET on the Monday of the expiry week (= 3rd Friday of expiry month − 4 days)
- Confirmed against TradingView export for Sep-2025, Dec-2025, Mar-2026 rolls
- In UTC: 22:00 UTC during EDT (Mar–Nov), 23:00 UTC during EST (Nov–Mar)

## Auto level generation methodology
Derived from Mancini Pine Script v5.3, adapted and corrected. Implemented in `backend/auto_levels.py`.

### Anchor
- Aggregate 1-min parquet data into 15-min bars
- Find the most recent 15-min bar whose close time = 4:00 PM ET (bar opens 3:45 PM, closes 4:00 PM)
- `close4pm` = close price of that bar; this is the price reference for all classification

### Pivot detection
- Confirm pivot highs and lows using N bars on each side (default N=5, configurable)
- A pivot high at bar i: `high[i] > high[i-k]` and `high[i] > high[i+k]` for all k in [1..N]
- Only pivots with timestamp ≤ 4pm anchor bar are considered (no future data leakage)

### Level classification
- Classification is by price location relative to `close4pm`, not pivot type
  - Pivot (high or low) with price > `close4pm` → resistance
  - Pivot (high or low) with price < `close4pm` → support
- Pivots processed newest-first; deduplication: skip if within `minSpacing` pts of any accepted level

### ML scoring (Phase 6e)
- After dedup (~108 candidates/day), every level is scored 0–1 by `data/phase6e_model.json` (XGBoost)
- `major = score ≥ 0.5` (solid line); below 0.5 = minor (dashed line)
- Falls back to bounce/touches heuristic if model file not available
- Top features: dist_from_4pm, sr_flip, recency_rank, local_density, price_crossings, round-number proximity

### Validation results (4/13/2026 vs Mancini's published levels)
- Supports: 41/42 matched ±2pt (98%); 31 extras (genuine pivots Mancini curates out)
- Resistances: 24/36 matched ±2pt (67%); 12 misses in the ATH zone (7048–7139)
- ATH gap is structural: market ran through that zone without forming clean confirmed pivots

### Configurable parameters (Auto Levels tab in ⚙ settings)
| Parameter | Default | Notes |
|---|---|---|
| Pivot lookback (bars/side) | 5 | integer |
| Price range (±pts) | 325 | float |
| Min level spacing (pts) | 3.0 | float |
| Touch zone (±pts) | 2.0 | float |
| Major bounce threshold (pts) | 40 | float — classification only |
| Major touch threshold | 12 | integer — classification only |
| Bounce forward window (bars) | 10 | integer — classification only |
| Min score | 0.0 | float 0–0.95 — client-side filter on ML score; "off" at 0 |
| Show major only | false | toggle |
| Show supports | true | toggle |
| Show resistances | true | toggle |

### Storage and UI
- Auto levels are NOT saved to levels.db — computed in memory only
- Date picker: the day levels are FOR (anchor = prior trading day's 4pm); blank = most recent 4pm in parquet
- Auto levels stay pinned to selected date; they do NOT update when a trade is clicked
- Manual and auto levels each have an independent on/off toggle in the right panel
- supports_raw / resistances_raw returned by backend (sorted: resistances ascending, supports descending)
- Min score filter is client-side: score field is on every returned level; no re-fetch needed when slider moves

## What's next
One remaining task:
- **ATH cluster detection** — after standard dedup, scan for top-N highest pivot highs in the lookback window not already within 5pts of an accepted level; captures the 12 missing ATH resistances that pivot geometry misses near the top of the prior move

## Research conclusions (major/minor study — fully exhausted)
We studied whether Mancini's major/minor distinction (the `(major)` tag in levels.db) could be predicted from the features available. It cannot, with any reliability:
- Proximity to close4pm: not a factor (42% major rate flat across all distance bands)
- Recency of pivot: statistically significant but tiny difference (median 10 vs 11 days); when two levels are close together, the major is the more recent one only 52% of the time
- Major-major spacing: 93% of major-major gaps ≥ 6pts (real pattern), but ML score cannot pick which of a close pair is major — bounce/recency are coin flips within close pairs
- Best decision tree accuracy: 59.7% (baseline 58.4%) — barely above guessing
- Conclusion: Mancini's major/minor reflects holistic judgment not reconstructible from pivot geometry alone. The `min_score` filter is the right lever for controlling clutter.
- See `docs/auto_level_study.md` for full methodology and all phase results

## Known issues / gotchas
- CSV column is `volume` (no typo)
- Databento prices are already in dollar format — no scaling needed
- On Windows, if Excel has the trade log open with an exclusive lock, pandas read will fail — close Excel first
- python-dotenv is installed in the venv and used by trades_manager.py
- Python command on this system: `python` (3.12.11)
- First backend start after adding es_front_month.parquet builds the file (~30s), subsequent starts load from RAM in ~1s
- es_1m.parquet: 73MB raw source (DO NOT DELETE); es_front_month.parquet: ~25MB preprocessed (can be rebuilt)
- DATA_START='2016-03-29' is a const in App.jsx; DATA_END is useState('2026-03-25') and updates after a successful download
- Databento pipeline lag: subscription tier has ~13hr lag; two successive 422s occur (pipeline limit, then subscription cap); downloader loops up to 4 times backing off 1 min each time
- TradingView CSV export: MES1! or ES1!, 1-min, no volume column — volume=0 set on import
- Download modal "From" field: read-only, auto-set to exact UTC timestamp of last bar in parquet
- Download modal "Done" message shows exact ET timestamp of last downloaded bar
- databento Python package: v0.74.1 installed in venv
- start.bat corruption: `venv\Scripts\activate` was corrupted to `vnot bpts\activate` at some point — if backend fails to start, check start.bat

## User preferences
- Visual-first: always keep the app in a runnable state
- Never break working features to add new ones
- Ask before making architectural changes
- Keep CLAUDE.md up to date at the end of every session
