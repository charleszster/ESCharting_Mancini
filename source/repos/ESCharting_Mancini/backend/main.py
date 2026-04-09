from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from data_manager import get_candles, parse_timeframe, warm_cache
from trades_manager import get_trades
from levels_manager import get_available_dates, get_levels, save_levels, reimport_from_excel
from downloader import get_estimate, stream_download


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
