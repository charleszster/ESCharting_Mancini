# ES Trade Analyzer — Technical Reference

A local desktop web application for reviewing ES futures trades against a candlestick chart, with Mancini-style support/resistance levels, price back-adjustment, and data management tools.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, Uvicorn |
| Data | Pandas, PyArrow/Parquet, NumPy, SQLite (via stdlib `sqlite3`) |
| Frontend | React 18 (Vite), TradingView Lightweight Charts v5 |
| Data source | Databento (GLBX.MDP3, `ohlcv-1m` schema) |
| Trade log | Excel (`.xlsm`) read via openpyxl |
| Configuration | python-dotenv (`.env` file) |
| Launch | `start.bat` — opens backend in separate CMD window, frontend in bat window |

---

## Project Structure

```
ESCharting_Mancini/
├── data/
│   ├── es_1m.parquet          # Raw 1-min OHLCV, all ES contracts (73 MB, DO NOT DELETE)
│   ├── es_front_month.parquet # Pre-processed front-month + adj_offset (~25 MB, rebuildable)
│   └── levels.db              # SQLite — Mancini manual support/resistance levels
├── backend/
│   ├── main.py                # FastAPI app, all route definitions
│   ├── data_manager.py        # Parquet loading, roll calendar, candle aggregation, RAM cache
│   ├── auto_levels.py         # Mancini-style auto level generation
│   ├── levels_manager.py      # SQLite CRUD for manual levels
│   ├── trades_manager.py      # Read-only Excel trade log parser
│   ├── downloader.py          # Databento download + TradingView CSV import
│   ├── import_levels.py       # One-time Excel→SQLite import utility
│   ├── roll_manager.py        # (stub, roll logic lives in data_manager.py)
│   └── venv/                  # Python virtual environment
├── frontend/
│   └── src/
│       ├── App.jsx                          # Root component, global state, layout
│       ├── components/
│       │   ├── Chart.jsx                    # LWC chart wrapper, all chart logic
│       │   ├── TradeList.jsx                # Left panel — scrollable trade list
│       │   ├── TradeDetail.jsx              # Right panel — trade P&L detail
│       │   ├── LevelsPanel.jsx              # Right panel — levels editor + auto levels UI
│       │   ├── ChartSettings.jsx            # Settings modal (7 tabs)
│       │   ├── DownloadModal.jsx            # Databento + TradingView CSV import modal
│       │   ├── DatabentoDownloader.jsx      # SSE progress UI for Databento
│       │   ├── TimeframeSelector.jsx        # Timeframe buttons
│       │   └── AdjustmentToggle.jsx         # Adj/Non-Adj toggle button
│       └── lib/
│           ├── TradeMarkers.js              # LWC v5 custom primitive — trade arrows
│           ├── LevelLabels.js               # LWC v5 custom primitive — level labels at right edge
│           └── SessionHighlight.js          # LWC v5 custom primitive — ETH/RTH shading
├── start.bat                  # Launch script (double-click to run app)
├── .env                       # DATABENTO_API_KEY, TRADES_FILE, TRADES_SHEET, LEVELS_FILE
├── CLAUDE.md                  # AI assistant project memory
└── TECHNICAL.md               # This file
```

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/` | Health check |
| GET | `/candles/bounds` | Actual min/max dates in parquet |
| GET | `/candles` | OHLCV candles — params: `timeframe`, `start`, `end`, `adjusted` |
| GET | `/trades` | All trades from Excel, newest-first |
| GET | `/levels` | Manual levels for a date (or most recent if no date) |
| PUT | `/levels` | Save/update levels for a date |
| GET | `/levels/dates` | All available dates in levels.db |
| GET | `/levels/auto` | Compute auto levels — all params configurable via query string |
| POST | `/levels/reimport` | Re-read Excel and upsert all rows into levels.db |
| GET | `/download/estimate` | Cost + size estimate for a Databento date range |
| GET | `/download/stream` | SSE stream — download, append, rebuild cache |
| POST | `/import/tv` | Accept TradingView CSV upload, append to parquet |

---

## Major Subsystems

### 1. Data Pipeline

**Source**: Databento `GLBX.MDP3` dataset, `ohlcv-1m` schema, `ES.FUT` parent symbol.  
**Raw store**: `data/es_1m.parquet` — all individual ES outright contract bars (ESH6, ESM6, …), unmodified. Never deleted.

**Pre-processing** (`data_manager.build_front_month_parquet`):
1. Load raw parquet, filter to outright ES symbols (regex `^ES[HMUZ]\d+$`)
2. Apply the roll calendar to assign each minute bar to the active front-month contract
3. Compute `adj_offset` for each contract segment (additive back-adjustment, see below)
4. Write `data/es_front_month.parquet` — one row per minute, front-month only, with `adj_offset` column

**RAM cache** (`data_manager._cache`): The front-month parquet is loaded into a Pandas DataFrame at startup (`warm_cache()`). All candle queries hit this in-memory cache — no disk I/O per request. Index is `ts_event` (UTC `datetime64`).

**Candle serving** (`data_manager.get_candles`):
- Slice cache by ET calendar date (binary search on UTC index)
- Apply `adj_offset` to OHLC if `adjusted=True`
- Resample in **ET timezone** (so 5-min bars align to :00/:05/:10… ET, matching TradingView)
- Convert back to UTC for the response; timestamps are Unix seconds

---

### 2. Roll Calendar & Back-Adjustment

**Rule**: Roll at 18:00 ET on the Monday of ES expiry week. Expiry week = the week of the 3rd Friday of the expiry month (March, June, September, December). Monday = 3rd Friday − 4 days.

**UTC conversion**: 22:00 UTC during EDT (Mar–Nov), 23:00 UTC during EST (Nov–Mar).

**Why this works**: Confirmed against TradingView MES1!/ES1! export for Sep-2025, Dec-2025, and Mar-2026 rolls. Max price diff vs TV = 10 pts (within feed-noise tolerance).

**Back-adjustment** (`data_manager.build_front_month_parquet`):
- Additive method: `adjusted_price = raw_price + adj_offset`
- `adj_offset` = 0.0 for the most recent contract segment, cumulative sum of roll spreads for older segments
- Roll spread at each boundary = `first_new_bar_close − old_contract_close_at_same_timestamp`
- Critical: both prices are sampled at the **same timestamp** (18:00 ET Globex reopen, when both contracts trade simultaneously). Using the old contract's last bar before roll would inflate the spread due to the 17:00–18:00 ET CME maintenance gap.
- Validated against TV MES1! daily closes: MAD ≈ 1.2 pts, within-period drift ≈ 0

**Symbol format**: Roll calendar uses 1-digit year (`ESH6`). Databento API may return 2-digit year (`ESH26`); `downloader._normalize_symbol()` converts on import.

---

### 3. Auto Level Generation

**File**: `backend/auto_levels.py`  
**Endpoint**: `GET /levels/auto`  
**Methodology**: Derived from Mancini Pine Script v5.3, adapted and corrected.

#### Step-by-step algorithm

**1. Resample to 15-min bars (ET-aligned)**
- Take the front-month RAM cache (1-min, UTC)
- Convert index to ET, resample with `pandas.resample('15min')` using OHLCV aggregation
- Result: 15-min bars labeled by bar-open time in ET

**2. Find the 4pm anchor bar**
- Look for bars where `hour == 15` and `minute == 45` on weekdays
  - On a 15-min ET chart, the bar labeled 15:45 *closes* at 16:00 ET — this is the 4pm close bar
- If `target_date` is provided: use strict `<` cutoff so Monday → Friday's 4pm (not Monday's)
- `close4pm` = the close of this bar; this is the price reference for all classification

**3. Pivot detection (vectorised)**
```python
# Pivot high at index i: highs[i] > highs[i±k] for all k in 1..N
# Pivot low at index i: lows[i] < lows[i±k] for all k in 1..N
# Only applied to the historical slice (bars ≤ 4pm anchor)
```
- Implemented with NumPy boolean arrays — O(N×pivot_len), no Python loops over bars
- Default N=5 (bars on each side); configurable

**4. Candidate filtering**
- Keep only pivots within ±`price_range` pts of `close4pm` (default ±250)
- Sort **newest-first** — most recent test of a price zone wins deduplication
- Deduplication: skip a candidate if any already-accepted level is within `min_spacing` pts (default 3.0)

**5. Level classification**
- Classification is by **price location relative to `close4pm`**, not pivot type:
  - price > close4pm → **resistance**
  - price < close4pm → **support**
- This correctly handles "prior support acting as resistance" and vice versa
- (Pine Script maps pivot highs → resistance, pivot lows → support, which is wrong when price crosses)

**6. Bounce measurement (strength signal)**
- Bounce follows **pivot type**, not the support/resistance classification:
  - Pivot high at price P, index `i`: `bounce = P − min(lows[i+1 .. i+forward_bars])`
  - Pivot low at price P, index `i`: `bounce = max(highs[i+1 .. i+forward_bars]) − P`
- This measures historical rejection magnitude, regardless of current role
- Default `forward_bars = 100` (= 25 hours on 15-min bars)
- The forward window uses the **full** 15-min array (not just history), so post-4pm price action contributes to bounce — this is intentional (it measures how strong the level proved to be)

**7. Touch counting (confluence signal)**
- Count all pivot highs AND pivot lows (in the historical slice) within ±`touch_zone` pts of P
- Default `touch_zone = 2.0` pts
- Forward touches excluded — no data leakage

**8. Major vs. minor classification**
```python
is_major = bounce >= maj_bounce OR touches >= maj_touches
# defaults: maj_bounce=40 pts, maj_touches=5
```
- Major → solid line on chart
- Minor → dashed line

**9. Output**
- Returns `supports` and `resistances` as lists of `{price, price_lo, price_hi, major, label}`
- Also returns `supports_raw` and `resistances_raw` — human-readable comma-separated strings (same format as manual levels)
- Supports sorted descending (nearest first above market); resistances ascending (nearest first below market)
- NOT saved to `levels.db` — computed in memory only, displayed in read-only UI section

**Configurable parameters** (all passed as query string to `/levels/auto`):

| Parameter | Default | Effect |
|---|---|---|
| `pivot_len` | 5 | Bars on each side required to confirm a pivot |
| `price_range` | 250 | Max distance from close4pm to include a level |
| `min_spacing` | 3.0 | Min gap between accepted levels (dedup radius) |
| `touch_zone` | 2.0 | Radius for counting touches |
| `maj_bounce` | 40 | Bounce threshold for major classification (pts) |
| `maj_touches` | 5 | Touch count threshold for major classification |
| `forward_bars` | 100 | Bars ahead used for bounce measurement |
| `show_major_only` | false | Filter to major levels only |
| `show_supports` | true | Include supports |
| `show_resistances` | true | Include resistances |

---

### 4. Manual Levels

**Storage**: `data/levels.db` (SQLite), table `levels(trading_date TEXT PRIMARY KEY, supports TEXT, resistances TEXT, source TEXT)`.

**Level string format**: Comma-separated tokens. Each token is either:
- A plain price: `6500`
- A price with flag: `6500 (major)`
- A price range: `6525-30` (4+2 digit shorthand → 6525/6530) or `5495-5500`

**Parsing** (`levels_manager._parse_token`): Regex handles all three forms. Range midpoint = plotted price; `price_lo`/`price_hi` are the bounds (drawn as a translucent zone).

**API behavior**:
- `GET /levels` with no `date` → most recent entry (for default view / after reset)
- `GET /levels?date=YYYY-MM-DD` → most recent entry on or before that date (for trade review)
- `PUT /levels` → upsert (insert or replace); returns updated row
- `POST /levels/reimport` → re-reads the Excel source and upserts all rows

**Trade click behavior**: clicking a trade auto-loads levels for that trade's date AND forces non-adjusted mode.

---

### 5. Trade Log Reader

**File**: `backend/trades_manager.py`  
**Source**: Excel `.xlsm` file, read-only via openpyxl.

**Dynamic exit detection**: Column headers are scanned with regex `^Exit (\d+) Date$` to discover how many exit legs exist — handles any number of exits without code changes.

**Time handling**: Excel stores dates and times in separate cells; `_to_utc_ts()` combines them, localizes to ET, and converts to UTC unix timestamp.

**Direction**: `Entry Qty > 0` = long, `< 0` = short.

---

### 6. Databento Download

**File**: `backend/downloader.py`  
**Pattern**: All Databento calls run in a `ThreadPoolExecutor` (single worker) so they don't block the async FastAPI event loop, and can't stomp each other.

**Retry loop** (`_resolve_end`): Databento returns HTTP 422 when the requested end date exceeds what's available. The error message contains the actual available end timestamp. The downloader parses this, backs off by 1 minute, and retries — up to 4 times. Two successive 422s are common: first the pipeline lag limit, then the subscription tier cap.

**SSE streaming** (`stream_download`): The `/download/stream` endpoint is an async generator that yields `data: {...}\n\n` JSON lines. Stages: connect → download → append → rebuild → done/error. The frontend uses `EventSource` to consume this.

**Append + dedup**: New data is concatenated with existing parquet and deduplicated on `(ts_event, symbol)` before writing. Front-month parquet is then rebuilt from scratch.

---

### 7. TradingView CSV Import

**Motivation**: Databento has a ~13hr pipeline lag on the subscription tier (e.g., at 7pm ET, data is only available through ~11am ET that day). TradingView shows the full day immediately after 4pm close.

**Format**: MES1! or ES1!, 1-min, columns: `time, open, high, low, close` (no volume). Timestamps are ISO-8601 with UTC offset.

**Processing**: TV timestamps → UTC, `volume=0`, symbol assigned from roll calendar (same logic as Databento data). Deduped against existing parquet on append.

---

### 8. Frontend Architecture

**Root** (`App.jsx`): Manages all global state — selected trade, date range, adjusted mode, levels, timeframe, chart settings. Passes data down as props; events bubble up via callbacks.

**Chart** (`Chart.jsx`): Creates and manages the LWC chart instance. Handles:
- Fetching candle data from `/candles`
- Rendering trade markers, level lines, and session highlights via custom primitives
- Crosshair mode switching
- Zoom-to-trade on trade click

**Custom LWC v5 Primitives** (in `frontend/src/lib/`): LWC v5 introduced the Primitive API for canvas drawing. Three primitives are registered as series-attached plugins:

- **`TradeMarkers.js`**: Draws up/down arrows pinned to entry/exit prices. Uses `priceToCordinate()` + `timeToCoordinate()` for positioning. Draws a white halo circle, then a filled triangle, then a text label with background box.

- **`LevelLabels.js`**: Draws level labels at the right edge of the chart, colored by type (green/red), with optional background box. Handles zone fill (translucent rectangle between `price_lo` and `price_hi`).

- **`SessionHighlight.js`**: Shades ETH (extended trading hours) vs RTH windows. Implemented by computing RTH windows (9:30–16:00 ET Mon–Fri) and shading the gaps *between* RTH windows. This avoids the "Sunday gap" bug where shading a UTC calendar day fails because timestamps in the gap return `null` from `timeToCoordinate`.

**Settings modal** (`ChartSettings.jsx`): 7 tabs — Candles, Grid, Sessions, Volume, Scales, Crosshair, Markers, Auto Levels. All settings stored in React state and passed as props to Chart.

---

### 9. Back-Adjustment Validation

- Computed `adj_offset` was validated against TradingView's MES1! continuous contract
- Method: export TV daily closes, compare to our adjusted daily closes for the same dates
- Result: MAD ≈ 1.2 pts (within feed-noise tolerance), within-period drift ≈ 0
- The key insight: TV uses the contemporaneous spread (both contracts at the same instant), not prices on different bars. Our implementation matches this.

---

## Environment & Configuration

**`.env` file** (project root):
```
DATABENTO_API_KEY=your_key_here
TRADES_FILE=C:\path\to\Trades - MES.xlsm
TRADES_SHEET=Consolidated Mancini FBD Trades
LEVELS_FILE=C:\path\to\trade_plans_running_list.xlsm
```

**Python venv**: `backend/venv/`. Key packages: `fastapi`, `uvicorn`, `pandas`, `pyarrow`, `numpy`, `openpyxl`, `python-dotenv`, `databento==0.74.1`, `python-multipart`.

**Data files**:
- `data/es_1m.parquet` — 73 MB, raw source, never delete
- `data/es_front_month.parquet` — ~25 MB, auto-rebuilt if missing
- `data/levels.db` — SQLite, ~50 KB

**Startup**: `start.bat` runs `uvicorn main:app --port 8000` (backend) and `npm run dev` (frontend). On first start after a new parquet, building `es_front_month.parquet` takes ~30s. Subsequent starts load from disk in ~1s.

---

## Known Gotchas

- **Databento prices**: already in dollar format (`float`). Older `databento-python` versions returned fixed-point int64 (×1e9); `_normalize_df()` detects and converts this automatically.
- **Excel lock**: if Excel has the trade log open with an exclusive lock, `openpyxl` read fails. Close Excel first.
- **start.bat**: the `venv\Scripts\activate` line has been corrupted to `vnot bpts\activate` at least once. If backend fails to start silently, check this line.
- **TradingView CSV volume**: TV claims to export volume, but the downloaded CSV has no volume column. `volume=0` is set on import — harmless for chart display and auto levels (which use OHLC only).
- **Databento pipeline lag**: ~13hr on the subscription tier. Two successive 422s are normal; the retry loop handles them automatically.
- **Roll calendar**: generates rolls from 2015–2028 at construction time. Add more years to `build_roll_calendar()` if needed.
