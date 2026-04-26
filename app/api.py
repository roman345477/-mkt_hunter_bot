"""
FastAPI — deals, settings, activity, Mini App.
"""

import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database import get_stats, get_deals, init_db, get_scrape_stats
from deal_engine import get_price_cache_info
import deal_engine as de

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Marktplaats Hunter", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

FRONTEND_DIR = Path("/app/frontend")
if not FRONTEND_DIR.exists():
    FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

_settings = {
    "min_discount":   de.MIN_DISCOUNT_PCT,
    "watch_discount": de.WATCH_DISCOUNT_PCT,
    "min_profit":     de.MIN_PROFIT_EUR,
    "max_price":      de.MAX_PRICE_EUR,
    "min_ram":        de.MIN_RAM,
    "gpus":           list(de.ALLOWED_GPUS),
}


class Settings(BaseModel):
    min_discount:   float = 15
    watch_discount: float = 10
    min_profit:     float = 100
    max_price:      float = 1000
    min_ram:        int   = 16
    gpus:           list  = ["RTX 4050", "RTX 4060"]


@app.on_event("startup")
async def startup():
    init_db()
    logger.info("API ready")


@app.get("/health")
async def health():
    return {"status": "ok", "stats": get_stats()}


@app.get("/settings")
async def get_settings():
    return _settings


@app.post("/settings")
async def update_settings(s: Settings):
    _settings.update(s.dict())
    de.MIN_DISCOUNT_PCT   = s.min_discount
    de.WATCH_DISCOUNT_PCT = s.watch_discount
    de.MIN_PROFIT_EUR     = s.min_profit
    de.MAX_PRICE_EUR      = s.max_price
    de.MIN_RAM            = s.min_ram
    de.ALLOWED_GPUS       = s.gpus if s.gpus else ["RTX 4050", "RTX 4060"]
    logger.info(f"Settings updated: {_settings}")
    return {"status": "ok", "settings": _settings}


@app.get("/deals")
async def deals_endpoint(
    limit:         int   = Query(50, le=200),
    offset:        int   = Query(0, ge=0),
    min_profit:    float = Query(0),
    gpu:           Optional[str] = Query(None),
    max_price:     float = Query(9999),
    sort_by:       str   = Query("score"),
    all:           bool  = Query(False),
    include_watch: bool  = Query(False),
):
    rows = get_deals(
        only_deals=not all, include_watch=include_watch,
        limit=limit, offset=offset, min_profit=min_profit,
        gpu=gpu, max_price=max_price, sort_by=sort_by,
    )
    return {"count": len(rows), "deals": rows}


@app.get("/latest")
async def latest_endpoint(limit: int = Query(30, le=100)):
    rows = get_deals(only_deals=False, include_watch=False, limit=limit, sort_by="newest")
    return {"count": len(rows), "listings": rows}


@app.get("/activity")
async def activity():
    return {
        "scrape_log":    get_scrape_stats(),
        "market_prices": get_price_cache_info(),
    }


@app.get("/deals/{item_id}")
async def get_deal(item_id: str):
    rows = get_deals(only_deals=False, include_watch=True, limit=500)
    match = next((r for r in rows if r["item_id"] == item_id), None)
    if not match:
        raise HTTPException(404, "Not found")
    return match


@app.get("/app")
async def mini_app():
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return JSONResponse({"error": "Frontend not found"}, status_code=404)


@app.get("/")
async def root():
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {"message": "Marktplaats Hunter API", "docs": "/docs"}
