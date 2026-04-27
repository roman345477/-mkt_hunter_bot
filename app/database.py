"""
Database — SQLite with all fields + persistent settings + price cache + price history.
"""

import sqlite3
import logging
import json
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
            ram              INTEGER DEFAULT 0,
            storage          INTEGER DEFAULT 0,
            screen           REAL DEFAULT 0,
            cpu              TEXT DEFAULT '',
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
            last_seen        TEXT DEFAULT (datetime('now')),
            is_active        INTEGER DEFAULT 1,
            price_history    TEXT DEFAULT '[]',
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

        CREATE TABLE IF NOT EXISTS kv_store (
            key        TEXT PRIMARY KEY,
            value      TEXT NOT NULL,
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_is_deal   ON deals(is_deal);
        CREATE INDEX IF NOT EXISTS idx_is_watch  ON deals(is_watch);
        CREATE INDEX IF NOT EXISTS idx_score     ON deals(deal_score DESC);
        CREATE INDEX IF NOT EXISTS idx_created   ON deals(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_notified  ON deals(notified);
        CREATE INDEX IF NOT EXISTS idx_gpu       ON deals(gpu);
        CREATE INDEX IF NOT EXISTS idx_active    ON deals(is_active);
        CREATE INDEX IF NOT EXISTS idx_last_seen ON deals(last_seen);
    """)

    # Migrate old schema
    migrations = [
        ("storage",       "INTEGER DEFAULT 0"),
        ("screen",        "REAL DEFAULT 0"),
        ("cpu",           "TEXT DEFAULT ''"),
        ("listed_date",   "TEXT"),
        ("last_seen",     "TEXT"),
        ("is_active",     "INTEGER DEFAULT 1"),
        ("price_history", "TEXT DEFAULT '[]'"),
    ]
    for col, defval in migrations:
        try:
            conn.execute(f"ALTER TABLE deals ADD COLUMN {col} {defval}")
        except Exception:
            pass

    conn.commit()
    conn.close()
    logger.info("DB initialized")


# ── KV Store ──────────────────────────────────────────────────────────────────

def kv_set(key: str, value):
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO kv_store (key, value, updated_at) VALUES (?, ?, datetime('now'))",
        (key, json.dumps(value))
    )
    conn.commit()
    conn.close()


def kv_get(key: str, default=None):
    conn = get_conn()
    row = conn.execute("SELECT value FROM kv_store WHERE key=?", (key,)).fetchone()
    conn.close()
    if row:
        try:
            return json.loads(row[0])
        except Exception:
            return default
    return default


# ── Settings ──────────────────────────────────────────────────────────────────

def save_settings(settings: dict):
    kv_set("settings", settings)


def load_settings() -> Optional[dict]:
    return kv_get("settings")


# ── Market price persistence ──────────────────────────────────────────────────

def save_price_cache(cache: dict):
    serializable = {}
    for gpu, data in cache.items():
        d = dict(data)
        if hasattr(d.get("updated"), "isoformat"):
            d["updated"] = d["updated"].isoformat()
        serializable[gpu] = d
    kv_set("price_cache", serializable)


def load_price_cache() -> dict:
    from datetime import datetime
    raw = kv_get("price_cache", {})
    result = {}
    for gpu, data in raw.items():
        d = dict(data)
        if isinstance(d.get("updated"), str):
            try:
                d["updated"] = datetime.fromisoformat(d["updated"])
            except Exception:
                d["updated"] = datetime.utcnow()
        result[gpu] = d
    return result


# ── Deals ─────────────────────────────────────────────────────────────────────

def upsert_deal(d: dict) -> bool:
    conn = get_conn()
    try:
        existing = conn.execute(
            "SELECT item_id, price, price_history FROM deals WHERE item_id=?",
            (d["item_id"],)
        ).fetchone()

        if existing:
            history  = json.loads(existing["price_history"] or "[]")
            old_price = existing["price"]
            new_price = d.get("price", old_price)

            if abs(new_price - old_price) > 1:
                history.append({
                    "price": old_price,
                    "ts": __import__("datetime").datetime.utcnow().isoformat()
                })
                history = history[-10:]
                conn.execute(
                    "UPDATE deals SET last_seen=datetime('now'), is_active=1, price=?, price_history=? WHERE item_id=?",
                    (new_price, json.dumps(history), d["item_id"])
                )
            else:
                conn.execute(
                    "UPDATE deals SET last_seen=datetime('now'), is_active=1 WHERE item_id=?",
                    (d["item_id"],)
                )
            conn.commit()
            return False

        conn.execute("""
            INSERT INTO deals (
                item_id,title,price,gpu,ram,storage,screen,cpu,condition,location,
                url,image_url,seller_name,description,scraped_at,listed_date,
                market_price,resale_price,profit,profit_percent,discount_percent,
                risk,liquidity,is_deal,is_watch,deal_score,price_history
            ) VALUES (
                :item_id,:title,:price,:gpu,:ram,:storage,:screen,:cpu,:condition,:location,
                :url,:image_url,:seller_name,:description,:scraped_at,:listed_date,
                :market_price,:resale_price,:profit,:profit_percent,:discount_percent,
                :risk,:liquidity,:is_deal,:is_watch,:deal_score,'[]'
            )
        """, d)
        conn.commit()
        return True
    finally:
        conn.close()


def mark_inactive(item_ids_seen: set):
    """Mark deals not seen in current scrape cycle as inactive."""
    if not item_ids_seen:
        return
    conn = get_conn()
    placeholders = ",".join("?" * len(item_ids_seen))
    conn.execute(f"""
        UPDATE deals
        SET is_active = 0
        WHERE is_active = 1
        AND last_seen < datetime('now', '-2 hours')
        AND item_id NOT IN ({placeholders})
    """, list(item_ids_seen))
    n = conn.execute("SELECT changes()").fetchone()[0]
    if n:
        logger.info(f"Marked {n} deals as inactive (sold/removed)")
    conn.commit()
    conn.close()


def get_price_dropped_deals() -> list:
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM deals
        WHERE is_active = 1
        AND (is_deal = 1 OR is_watch = 1)
        AND price_history != '[]'
        AND notified < 2
    """).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        history = json.loads(d.get("price_history") or "[]")
        if history:
            old_price = history[-1]["price"]
            current   = d["price"]
            drop_pct  = round((old_price - current) / max(old_price, 1) * 100, 1)
            if drop_pct >= 5:
                d["price_dropped_from"] = old_price
                d["price_drop_pct"]     = drop_pct
                result.append(d)
    return result


def mark_drop_notified(item_id: str):
    conn = get_conn()
    conn.execute("UPDATE deals SET notified=2 WHERE item_id=?", (item_id,))
    conn.commit()
    conn.close()


def mark_notified(item_id: str):
    conn = get_conn()
    conn.execute("UPDATE deals SET notified=1 WHERE item_id=? AND notified=0", (item_id,))
    conn.commit()
    conn.close()


def log_scrape(total_scraped: int, new_found: int, deals_found: int, watch_found: int = 0):
    conn = get_conn()
    conn.execute(
        "INSERT INTO scrape_log (total_scraped,new_found,deals_found,watch_found) VALUES (?,?,?,?)",
        (total_scraped, new_found, deals_found, watch_found)
    )
    conn.execute("DELETE FROM scrape_log WHERE id NOT IN (SELECT id FROM scrape_log ORDER BY id DESC LIMIT 100)")
    conn.commit()
    conn.close()


def get_scrape_stats() -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT scraped_at,total_scraped,new_found,deals_found,watch_found FROM scrape_log ORDER BY id DESC LIMIT 20"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def cleanup_old_records():
    conn = get_conn()
    n = conn.execute(
        "DELETE FROM deals WHERE created_at < datetime('now', '-30 days')"
    ).rowcount
    if n:
        logger.info(f"Cleaned {n} old records")
    conn.commit()
    conn.close()


def get_deals(
    only_deals: bool = True,
    include_watch: bool = False,
    only_active: bool = True,
    limit: int = 50,
    offset: int = 0,
    min_profit: float = 0,
    gpu: Optional[str] = None,
    max_price: float = 999999,
    sort_by: str = "score",
) -> list:
    conn = get_conn()
    filters, params = ["1=1"], []

    if only_deals and not include_watch:
        filters.append("is_deal=1")
    elif include_watch:
        filters.append("(is_deal=1 OR is_watch=1)")

    if only_active:
        filters.append("is_active=1")
    if min_profit > 0:
        filters.append("profit>=?"); params.append(min_profit)
    if gpu:
        filters.append("gpu=?"); params.append(gpu)
    if max_price < 999999:
        filters.append("price<=?"); params.append(max_price)

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


def get_pending_notifications() -> list:
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM deals
        WHERE (is_deal=1 OR is_watch=1) AND notified=0 AND is_active=1
        ORDER BY is_deal DESC, deal_score DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_stats() -> dict:
    conn = get_conn()
    s = conn.execute("""
        SELECT COUNT(*) as total,
            SUM(CASE WHEN is_deal=1 AND is_active=1 THEN 1 ELSE 0 END) as deals,
            SUM(CASE WHEN is_watch=1 AND is_active=1 THEN 1 ELSE 0 END) as watches,
            SUM(CASE WHEN is_active=0 THEN 1 ELSE 0 END) as sold,
            MAX(profit) as best_profit,
            AVG(CASE WHEN is_deal=1 THEN profit ELSE NULL END) as avg_profit
        FROM deals
    """).fetchone()
    conn.close()
    return dict(s) if s else {}
