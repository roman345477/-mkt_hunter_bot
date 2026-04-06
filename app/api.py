"""
FastAPI — deals API + watch + Mini App + activity log.
"""

import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from database import get_stats, get_deals, init_db, get_scrape_stats
from deal_engine import get_price_cache_info

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Marktplaats Hunter", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

FRONTEND_DIR = Path("/app/frontend")
if not FRONTEND_DIR.exists():
    FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


@app.on_event("startup")
async def startup():
    init_db()
    logger.info("API ready")


@app.get("/health")
async def health():
    return {"status": "ok", "stats": get_stats()}


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
        "scrape_log": get_scrape_stats(),
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
