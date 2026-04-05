"""
Database layer — SQLite with deduplication.
"""

import sqlite3
import logging
import json
from pathlib import Path
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = Path("data/deals.db")


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS deals (
            item_id          TEXT PRIMARY KEY,
            title            TEXT NOT NULL,
            price            REAL NOT NULL,
            gpu              TEXT NOT NULL,
            ram              INTEGER,
            condition        TEXT,
            location         TEXT,
            url              TEXT,
            image_url        TEXT,
            seller_name      TEXT,
            description      TEXT,
            scraped_at       TEXT,
            market_price     REAL,
            resale_price     REAL,
            profit           REAL,
            profit_percent   REAL,
            discount_percent REAL,
            risk             TEXT,
            liquidity        TEXT,
            is_deal          INTEGER DEFAULT 0,
            deal_score       REAL,
            notified         INTEGER DEFAULT 0,
            created_at       TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_is_deal   ON deals(is_deal);
        CREATE INDEX IF NOT EXISTS idx_score     ON deals(deal_score DESC);
        CREATE INDEX IF NOT EXISTS idx_created   ON deals(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_notified  ON deals(notified);
    """)
    conn.commit()
    conn.close()
    logger.info("DB initialized")


def upsert_deal(d: dict) -> bool:
    """Insert deal; return True if it's NEW (not seen before)."""
    conn = get_conn()
    try:
        cur = conn.execute("SELECT item_id FROM deals WHERE item_id = ?", (d["item_id"],))
        exists = cur.fetchone()
        if exists:
            return False

        conn.execute("""
            INSERT INTO deals (
                item_id, title, price, gpu, ram, condition, location,
                url, image_url, seller_name, description, scraped_at,
                market_price, resale_price, profit, profit_percent,
                discount_percent, risk, liquidity, is_deal, deal_score
            ) VALUES (
                :item_id, :title, :price, :gpu, :ram, :condition, :location,
                :url, :image_url, :seller_name, :description, :scraped_at,
                :market_price, :resale_price, :profit, :profit_percent,
                :discount_percent, :risk, :liquidity, :is_deal, :deal_score
            )
        """, d)
        conn.commit()
        return True
    finally:
        conn.close()


def mark_notified(item_id: str):
    conn = get_conn()
    conn.execute("UPDATE deals SET notified = 1 WHERE item_id = ?", (item_id,))
    conn.commit()
    conn.close()


def get_deals(
    only_deals: bool = True,
    limit: int = 50,
    offset: int = 0,
    min_profit: float = 0,
    gpu: Optional[str] = None,
    max_price: float = 9999,
    sort_by: str = "score",
) -> list[dict]:
    conn = get_conn()
    filters = ["1=1"]
    params: list = []

    if only_deals:
        filters.append("is_deal = 1")
    if min_profit > 0:
        filters.append("profit >= ?")
        params.append(min_profit)
    if gpu:
        filters.append("gpu = ?")
        params.append(gpu)
    if max_price < 9999:
        filters.append("price <= ?")
        params.append(max_price)

    order = {
        "score":  "deal_score DESC",
        "profit": "profit DESC",
        "newest": "created_at DESC",
        "price":  "price ASC",
    }.get(sort_by, "deal_score DESC")

    where = " AND ".join(filters)
    sql = f"""
        SELECT * FROM deals
        WHERE {where}
        ORDER BY {order}
        LIMIT ? OFFSET ?
    """
    params += [limit, offset]

    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_pending_notifications() -> list[dict]:
    """Return deals that haven't been sent to Telegram yet."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM deals
        WHERE is_deal = 1 AND notified = 0
        ORDER BY deal_score DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_stats() -> dict:
    conn = get_conn()
    stats = conn.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN is_deal = 1 THEN 1 ELSE 0 END) as deals,
            MAX(profit) as best_profit,
            AVG(CASE WHEN is_deal = 1 THEN profit ELSE NULL END) as avg_profit
        FROM deals
    """).fetchone()
    conn.close()
    return dict(stats) if stats else {}
