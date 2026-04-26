"""
Database — SQLite with dedup, scrape log, listed_date, auto-cleanup.
"""

import sqlite3
import logging
from pathlib import Path
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
            listed_date      TEXT,
            market_price     REAL,
            resale_price     REAL,
            profit           REAL,
            profit_percent   REAL,
            discount_percent REAL,
            risk             TEXT,
            liquidity        TEXT,
            is_deal          INTEGER DEFAULT 0,
            is_watch         INTEGER DEFAULT 0,
            deal_score       REAL,
            notified         INTEGER DEFAULT 0,
            created_at       TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS scrape_log (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            scraped_at    TEXT DEFAULT (datetime('now')),
            total_scraped INTEGER,
            new_found     INTEGER,
            deals_found   INTEGER,
            watch_found   INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_is_deal  ON deals(is_deal);
        CREATE INDEX IF NOT EXISTS idx_is_watch ON deals(is_watch);
        CREATE INDEX IF NOT EXISTS idx_score    ON deals(deal_score DESC);
        CREATE INDEX IF NOT EXISTS idx_created  ON deals(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_notified ON deals(notified);
        CREATE INDEX IF NOT EXISTS idx_listed   ON deals(listed_date DESC);
    """)
    # Add listed_date column if upgrading from old schema
    try:
        conn.execute("ALTER TABLE deals ADD COLUMN listed_date TEXT")
        conn.commit()
    except Exception:
        pass
    conn.commit()
    conn.close()
    logger.info("DB initialized")


def cleanup_old_records():
    conn = get_conn()
    deleted = conn.execute(
        "DELETE FROM deals WHERE created_at < datetime('now', '-30 days')"
    ).rowcount
    if deleted:
        logger.info(f"Cleaned up {deleted} old records")
    conn.commit()
    conn.close()


def log_scrape(total_scraped: int, new_found: int, deals_found: int, watch_found: int = 0):
    conn = get_conn()
    conn.execute(
        "INSERT INTO scrape_log (total_scraped, new_found, deals_found, watch_found) VALUES (?,?,?,?)",
        (total_scraped, new_found, deals_found, watch_found)
    )
    conn.execute("DELETE FROM scrape_log WHERE id NOT IN (SELECT id FROM scrape_log ORDER BY id DESC LIMIT 100)")
    conn.commit()
    conn.close()


def get_scrape_stats() -> list:
    conn = get_conn()
    rows = conn.execute("""
        SELECT scraped_at, total_scraped, new_found, deals_found, watch_found
        FROM scrape_log ORDER BY id DESC LIMIT 20
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def upsert_deal(d: dict) -> bool:
    conn = get_conn()
    try:
        if conn.execute("SELECT item_id FROM deals WHERE item_id = ?", (d["item_id"],)).fetchone():
            return False
        conn.execute("""
            INSERT INTO deals (
                item_id, title, price, gpu, ram, condition, location,
                url, image_url, seller_name, description, scraped_at, listed_date,
                market_price, resale_price, profit, profit_percent,
                discount_percent, risk, liquidity, is_deal, is_watch, deal_score
            ) VALUES (
                :item_id, :title, :price, :gpu, :ram, :condition, :location,
                :url, :image_url, :seller_name, :description, :scraped_at, :listed_date,
                :market_price, :resale_price, :profit, :profit_percent,
                :discount_percent, :risk, :liquidity, :is_deal, :is_watch, :deal_score
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
    include_watch: bool = False,
    limit: int = 50,
    offset: int = 0,
    min_profit: float = 0,
    gpu: Optional[str] = None,
    max_price: float = 9999,
    sort_by: str = "score",
) -> list[dict]:
    conn = get_conn()
    filters, params = ["1=1"], []

    if only_deals and not include_watch:
        filters.append("is_deal = 1")
    elif include_watch:
        filters.append("(is_deal = 1 OR is_watch = 1)")

    if min_profit > 0:
        filters.append("profit >= ?"); params.append(min_profit)
    if gpu:
        filters.append("gpu = ?"); params.append(gpu)
    if max_price < 9999:
        filters.append("price <= ?"); params.append(max_price)

    order = {
        "score":  "deal_score DESC, discount_percent DESC",
        "profit": "profit DESC",
        "newest": "created_at DESC",
        "price":  "price ASC",
        "listed": "listed_date DESC",
    }.get(sort_by, "deal_score DESC")

    rows = conn.execute(
        f"SELECT * FROM deals WHERE {' AND '.join(filters)} ORDER BY {order} LIMIT ? OFFSET ?",
        params + [limit, offset]
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_pending_notifications() -> list[dict]:
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM deals
        WHERE (is_deal = 1 OR is_watch = 1) AND notified = 0
        ORDER BY is_deal DESC, deal_score DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_stats() -> dict:
    conn = get_conn()
    stats = conn.execute("""
        SELECT COUNT(*) as total,
            SUM(CASE WHEN is_deal=1 THEN 1 ELSE 0 END) as deals,
            SUM(CASE WHEN is_watch=1 THEN 1 ELSE 0 END) as watches,
            MAX(profit) as best_profit,
            AVG(CASE WHEN is_deal=1 THEN profit ELSE NULL END) as avg_profit
        FROM deals
    """).fetchone()
    conn.close()
    return dict(stats) if stats else {}
