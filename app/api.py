"""
FastAPI — deals, settings, activity, market prices.
"""

import logging
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database import (
    get_stats, get_deals, init_db, get_scrape_stats,
    save_settings, load_settings
)
import deal_engine as de
import market_prices as mp

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Marktplaats Hunter", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

FRONTEND_DIR = Path("/app/frontend")
if not FRONTEND_DIR.exists():
    FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


def _apply(s: dict):
    de.MIN_DISCOUNT_PCT   = float(s.get("min_discount",   de.MIN_DISCOUNT_PCT))
    de.WATCH_DISCOUNT_PCT = float(s.get("watch_discount", de.WATCH_DISCOUNT_PCT))
    de.MIN_PROFIT_EUR     = float(s.get("min_profit",     de.MIN_PROFIT_EUR))
    de.MIN_PRICE_EUR      = float(s.get("min_price",      de.MIN_PRICE_EUR))
    de.MAX_PRICE_EUR      = float(s.get("max_price",      de.MAX_PRICE_EUR))
    de.MIN_RAM            = int(s.get("min_ram",          de.MIN_RAM))
    de.MIN_STORAGE        = int(s.get("min_storage",      de.MIN_STORAGE))
    de.MIN_SCREEN         = float(s.get("min_screen",     de.MIN_SCREEN))
    de.MAX_SCREEN         = float(s.get("max_screen",     de.MAX_SCREEN))
    de.ALLOWED_CPUS       = s.get("cpus", [])
    gpus = s.get("gpus", [])
    de.ALLOWED_GPUS       = list(gpus) if gpus else None


def _current_settings() -> dict:
    return {
        "min_discount":   de.MIN_DISCOUNT_PCT,
        "watch_discount": de.WATCH_DISCOUNT_PCT,
        "min_profit":     de.MIN_PROFIT_EUR,
        "min_price":      de.MIN_PRICE_EUR,
        "max_price":      de.MAX_PRICE_EUR,
        "min_ram":        de.MIN_RAM,
        "min_storage":    de.MIN_STORAGE,
        "min_screen":     de.MIN_SCREEN,
        "max_screen":     de.MAX_SCREEN,
        "gpus":           list(de.ALLOWED_GPUS) if de.ALLOWED_GPUS else [],
        "cpus":           list(de.ALLOWED_CPUS),
    }


class Settings(BaseModel):
    min_discount:   float     = 15
    watch_discount: float     = 10
    min_profit:     float     = 100
    min_price:      float     = 0
    max_price:      float     = 5000
    min_ram:        int       = 16
    min_storage:    int       = 0
    min_screen:     float     = 0
    max_screen:     float     = 0
    gpus:           List[str] = []
    cpus:           List[str] = []


@app.on_event("startup")
async def startup():
    init_db()
    saved = load_settings()
    if saved:
        _apply(saved)
        logger.info(f"Settings loaded — GPUs: {de.ALLOWED_GPUS}")
    logger.info("API ready")


@app.get("/health")
async def health():
    return {"status": "ok", "stats": get_stats()}


@app.get("/settings")
async def get_settings_ep():
    return _current_settings()


@app.post("/settings")
async def update_settings(s: Settings):
    d = s.dict()
    _apply(d)
    save_settings(d)
    logger.info(f"Settings saved — GPUs: {de.ALLOWED_GPUS}")
    return {"status": "ok", "settings": _current_settings()}


@app.get("/deals")
async def deals_endpoint(
    limit:            int   = Query(50, le=200),
    offset:           int   = Query(0, ge=0),
    min_profit:       float = Query(0),
    gpu:              Optional[str] = Query(None),
    max_price:        float = Query(999999),
    sort_by:          str   = Query("score"),
    all:              bool  = Query(False),
    include_watch:    bool  = Query(False),
    include_inactive: bool  = Query(False),
):
    rows = get_deals(
        only_deals    = not all,
        include_watch = include_watch,
        only_active   = not include_inactive,
        limit         = limit,
        offset        = offset,
        min_profit    = min_profit,
        gpu           = gpu,
        max_price     = max_price,
        sort_by       = sort_by,
    )
    return {"count": len(rows), "deals": rows}


@app.get("/latest")
async def latest_endpoint(limit: int = Query(30, le=100)):
    rows = get_deals(only_deals=False, only_active=True, limit=limit, sort_by="newest")
    return {"count": len(rows), "listings": rows}


@app.get("/activity")
async def activity():
    return {
        "scrape_log":    get_scrape_stats(),
        "market_prices": mp.all_prices_info(),
    }


@app.get("/gpus")
async def gpus_list():
    return {"gpus": mp.all_prices_info()}


@app.get("/deals/{item_id}")
async def get_deal(item_id: str):
    rows = get_deals(only_deals=False, include_watch=True, only_active=False, limit=500)
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
    return {"message": "Marktplaats Hunter v2", "docs": "/docs"}
