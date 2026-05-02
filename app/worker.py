"""
Worker — reads settings from DB every cycle so GPU filter applies immediately.
"""

import asyncio
import logging
import os
import signal

from scraper import scrape_all
from deal_engine import evaluate
from database import (
    init_db, upsert_deal, get_pending_notifications,
    mark_notified, log_scrape, cleanup_old_records,
    mark_inactive, get_price_dropped_deals, mark_drop_notified,
    load_settings
)
from telegram_bot import (
    send_deal_alert, send_watch_alert,
    send_price_drop_alert, notify_startup
)
import market_prices as mp
import deal_engine as de

logger = logging.getLogger(__name__)
SCRAPE_INTERVAL = int(os.getenv("SCRAPE_INTERVAL", "90"))
running = True
_cycle  = 0


def handle_signal(*_):
    global running
    running = False


def apply_settings(s: dict):
    """Apply settings dict to deal_engine module variables."""
    if not s:
        return
    de.MIN_DISCOUNT_PCT   = float(s.get("min_discount",   de.MIN_DISCOUNT_PCT))
    de.WATCH_DISCOUNT_PCT = float(s.get("watch_discount", de.WATCH_DISCOUNT_PCT))
    de.MIN_PROFIT_EUR     = float(s.get("min_profit",     de.MIN_PROFIT_EUR))
    de.MIN_PRICE_EUR      = float(s.get("min_price",      de.MIN_PRICE_EUR))
    de.MAX_PRICE_EUR      = float(s.get("max_price",      de.MAX_PRICE_EUR))
    de.MIN_RAM            = int(s.get("min_ram",          de.MIN_RAM))
    de.MIN_STORAGE        = int(s.get("min_storage",      de.MIN_STORAGE))
    de.MIN_SCREEN         = float(s.get("min_screen",     de.MIN_SCREEN))
    de.MAX_SCREEN         = float(s.get("max_screen",     de.MAX_SCREEN))
    gpus = s.get("gpus", [])
    # Only override if user explicitly selected GPUs
    if gpus:
        de.ALLOWED_GPUS = list(gpus)
    else:
        de.ALLOWED_GPUS = list(mp.known_gpus())
    de.ALLOWED_CPUS = s.get("cpus", [])


async def run_cycle():
    global _cycle
    _cycle += 1

    # Reload settings from DB every cycle — ensures GPU filter changes apply immediately
    saved = load_settings()
    if saved:
        apply_settings(saved)

    logger.info(f"▶ Cycle {_cycle} — allowed GPUs: {de.ALLOWED_GPUS}")

    listings = await scrape_all(max_price=int(de.MAX_PRICE_EUR))

    if not listings:
        log_scrape(0, 0, 0, 0)
        return

    mp.update_from_listings(listings)

    new_c = deal_c = watch_c = 0
    seen_ids: set = set()

    for l in listings:
        seen_ids.add(l["item_id"])
        d = evaluate(l)
        if d is None:
            continue
        d = d.to_dict()
        if upsert_deal(d):
            new_c += 1
            if d["is_deal"]:
                deal_c += 1
                logger.info(f"DEAL: {d['title'][:40]} €{d['price']} profit €{d['profit']}")
            elif d["is_watch"]:
                watch_c += 1
                logger.info(f"WATCH: {d['title'][:40]} €{d['price']} -{d['discount_percent']}%")

    mark_inactive(seen_ids)
    log_scrape(len(listings), new_c, deal_c, watch_c)
    logger.info(f"Done: {len(listings)} scraped, {new_c} new, {deal_c} deals, {watch_c} watches")

    for deal in get_pending_notifications():
        ok = await send_deal_alert(deal) if deal["is_deal"] else await send_watch_alert(deal)
        if ok:
            mark_notified(deal["item_id"])
        await asyncio.sleep(0.5)

    for deal in get_price_dropped_deals():
        ok = await send_price_drop_alert(deal)
        if ok:
            mark_drop_notified(deal["item_id"])
        await asyncio.sleep(0.5)

    if _cycle % 100 == 0:
        cleanup_old_records()


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    init_db()

    saved = load_settings()
    if saved:
        apply_settings(saved)
        logger.info(f"Settings loaded — GPUs: {de.ALLOWED_GPUS}")

    await notify_startup()
    logger.info(f"Worker started — interval {SCRAPE_INTERVAL}s")

    while running:
        try:
            await run_cycle()
        except Exception as e:
            logger.error(f"Cycle error: {e}", exc_info=True)
        for _ in range(SCRAPE_INTERVAL):
            if not running:
                break
            await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
