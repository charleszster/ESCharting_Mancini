from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from data_manager import get_candles, get_data_bounds, parse_timeframe, warm_cache
from trades_manager import get_trades
from levels_manager import get_available_dates, get_levels, save_levels, reimport_from_excel
from downloader import get_estimate, stream_download, import_tv_csv, _executor
from auto_levels import compute_auto_levels


@asynccontextmanager
async def lifespan(app: FastAPI):
    warm_cache()   # build es_front_month.parquet if needed, then load to RAM
    yield


app = FastAPI(title="ES Trade Analyzer", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def health():
    return {"status": "ok", "message": "ES Trade Analyzer backend running"}


@app.get("/trades")
def trades():
    try:
        data = get_trades()
        return {"count": len(data), "trades": data}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/levels/dates")
def levels_dates():
    return {"dates": get_available_dates()}


@app.get("/levels")
def levels(date: str | None = Query(default=None, description="ET date, e.g. 2026-04-06")):
    return get_levels(date)


class LevelsSave(BaseModel):
    date: str
    supports_raw: str
    resistances_raw: str


@app.put("/levels")
def levels_save(body: LevelsSave):
    try:
        return save_levels(body.date, body.supports_raw, body.resistances_raw)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/levels/auto")
def levels_auto(
    pivot_len:        int   = Query(default=5,     ge=2,   le=20),
    price_range:      float = Query(default=325.0, ge=50,  le=2000),
    min_spacing:      float = Query(default=3.0,   ge=0.25, le=20),
    touch_zone:       float = Query(default=2.0,   ge=0.25, le=10),
    maj_bounce:       float = Query(default=40.0,  ge=5,   le=200),
    maj_touches:      int   = Query(default=12,    ge=1,   le=30),
    forward_bars:     int   = Query(default=10,    ge=2,   le=500),
    show_major_only:  bool        = Query(default=False),
    show_supports:    bool        = Query(default=True),
    show_resistances: bool        = Query(default=True),
    min_score:        float       = Query(default=0.0, ge=0.0, le=1.0),
    ath_cluster_n:    int         = Query(default=15, ge=0, le=50),
    target_date:      str | None  = Query(default=None, description="ET date, e.g. 2026-04-08. Omit for most recent 4pm."),
):
    try:
        return compute_auto_levels(
            pivot_len=pivot_len, price_range=price_range, min_spacing=min_spacing,
            touch_zone=touch_zone, maj_bounce=maj_bounce, maj_touches=maj_touches,
            forward_bars=forward_bars, show_major_only=show_major_only,
            show_supports=show_supports, show_resistances=show_resistances,
            min_score=min_score, ath_cluster_n=ath_cluster_n, target_date=target_date,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/levels/reimport")
def levels_reimport():
    try:
        return reimport_from_excel()
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/download/estimate")
def download_estimate(
    start: str = Query(..., description="ET date, e.g. 2026-03-26"),
    end:   str = Query(..., description="ET date, e.g. 2026-04-09"),
):
    try:
        return get_estimate(start, end)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/download/stream")
async def download_stream(
    start: str = Query(..., description="ET date, e.g. 2026-03-26"),
    end:   str = Query(..., description="ET date, e.g. 2026-04-09"),
):
    return StreamingResponse(
        stream_download(start, end),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/import/tv")
async def import_tv(file: UploadFile = File(...)):
    """Accept a TradingView 1-min OHLC CSV export and append to es_1m.parquet."""
    import asyncio
    loop = asyncio.get_event_loop()
    try:
        contents = await file.read()
        result = await loop.run_in_executor(_executor, import_tv_csv, contents)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/candles/bounds")
def candles_bounds():
    return get_data_bounds()


@app.get("/candles")
def candles(
    timeframe: str  = Query(default="5",    description="Timeframe in minutes or 'D'"),
    start: str | None = Query(default=None, description="ET date, e.g. 2025-01-01"),
    end:   str | None = Query(default=None, description="ET date, e.g. 2025-01-31"),
    adjusted: bool  = Query(default=False,  description="Apply additive back-adjustment"),
):
    try:
        parse_timeframe(timeframe)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    data = get_candles(timeframe=timeframe, start=start, end=end, adjusted=adjusted)
    return {"timeframe": timeframe, "adjusted": adjusted, "count": len(data), "candles": data}
