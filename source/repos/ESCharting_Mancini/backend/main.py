from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from data_manager import get_candles, parse_timeframe, warm_cache
from trades_manager import get_trades


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


@app.get("/candles")
def candles(
    timeframe: str = Query(default="5", description="Timeframe in minutes or 'D'"),
    start: str | None = Query(default=None, description="ET date, e.g. 2025-01-01"),
    end:   str | None = Query(default=None, description="ET date, e.g. 2025-01-31"),
):
    try:
        parse_timeframe(timeframe)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    data = get_candles(timeframe=timeframe, start=start, end=end)
    return {"timeframe": timeframe, "count": len(data), "candles": data}
