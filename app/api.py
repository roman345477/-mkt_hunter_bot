"""
FastAPI server — serves deals API + hosts Mini App frontend.
"""

import os
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from database import get_stats, get_deals, init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Marktplaats Hunter API",
    version="1.0.0",
    docs_url="/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


@app.on_event("startup")
async def startup():
    init_db()
    logger.info("API ready")


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    stats = get_stats()
    return {"status": "ok", "stats": stats}


# ── Deals API ─────────────────────────────────────────────────────────────────

@app.get("/deals")
async def deals_endpoint(
    limit:      int   = Query(50, le=200),
    offset:     int   = Query(0, ge=0),
    min_profit: float = Query(0),
    gpu:        Optional[str] = Query(None),
    max_price:  float = Query(9999),
    sort_by:    str   = Query("score"),
    all:        bool  = Query(False),  # if true, return non-deals too
):
    rows = get_deals(
        only_deals  = not all,
        limit       = limit,
        offset      = offset,
        min_profit  = min_profit,
        gpu         = gpu,
        max_price   = max_price,
        sort_by     = sort_by,
    )
    return {"count": len(rows), "deals": rows}


@app.get("/latest")
async def latest_endpoint(limit: int = Query(20, le=100)):
    """Latest listings regardless of deal status."""
    rows = get_deals(only_deals=False, limit=limit, sort_by="newest")
    return {"count": len(rows), "listings": rows}


@app.get("/deals/{item_id}")
async def get_deal(item_id: str):
    rows = get_deals(only_deals=False, limit=1, sort_by="newest")
    # Filter in Python for simplicity (low traffic)
    conn_rows = get_deals(only_deals=False, limit=500)
    match = next((r for r in conn_rows if r["item_id"] == item_id), None)
    if not match:
        raise HTTPException(404, "Deal not found")
    return match


# ── Frontend (Mini App) ───────────────────────────────────────────────────────

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR / "static")), name="static")

    @app.get("/app")
    async def mini_app():
        index = FRONTEND_DIR / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return JSONResponse({"error": "Frontend not built"}, 404)

    @app.get("/")
    async def root():
        return FileResponse(str(FRONTEND_DIR / "index.html"))
else:
    @app.get("/")
    async def root():
        return {"message": "Marktplaats Hunter API", "docs": "/docs"}
