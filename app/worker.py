"""
Worker — runs the scrape → evaluate → notify loop.
Runs as a background process alongside the API.
"""

import asyncio
import logging
import os
import signal
import sys

from scraper import scrape_all
from deal_engine import evaluate
from database import init_db, upsert_deal, get_pending_notifications, mark_notified
from telegram_bot import send_deal_alert, notify_startup

logger = logging.getLogger(__name__)

SCRAPE_INTERVAL = int(os.getenv("SCRAPE_INTERVAL", "45"))  # seconds
running = True


def handle_signal(*_):
    global running
    logger.info("Shutdown signal received")
    running = False


async def run_cycle():
    logger.info("▶ Scrape cycle started")

    listings = await scrape_all()
    new_count  = 0
    deal_count = 0

    for listing in listings:
        evaluation = evaluate(listing)
        if evaluation is None:
            continue

        d = evaluation.to_dict()
        is_new = upsert_deal(d)
        if is_new:
            new_count += 1
            if d["is_deal"]:
                deal_count += 1
                logger.info(
                    f"💰 New deal: {d['title'][:40]} | "
                    f"€{d['price']} | profit €{d['profit']} ({d['profit_percent']}%) | "
                    f"risk={d['risk']} liq={d['liquidity']}"
                )

    logger.info(f"✅ Cycle done: {len(listings)} scraped, {new_count} new, {deal_count} deals")

    # Send Telegram notifications for pending deals
    pending = get_pending_notifications()
    for deal in pending:
        success = await send_deal_alert(deal)
        if success:
            mark_notified(deal["item_id"])
            await asyncio.sleep(0.5)


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    init_db()
    await notify_startup()

    logger.info(f"🔍 Worker started — interval {SCRAPE_INTERVAL}s")

    while running:
        try:
            await run_cycle()
        except Exception as e:
            logger.error(f"Cycle error: {e}", exc_info=True)

        # Wait for next cycle (interruptible)
        for _ in range(SCRAPE_INTERVAL):
            if not running:
                break
            await asyncio.sleep(1)

    logger.info("Worker stopped")


if __name__ == "__main__":
    asyncio.run(main())
