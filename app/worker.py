import asyncio
import logging
import os
import signal

from scraper import scrape_all
from deal_engine import evaluate, update_market_prices
from database import init_db, upsert_deal, get_pending_notifications, mark_notified, log_scrape
from telegram_bot import send_deal_alert, send_watch_alert, notify_startup

logger = logging.getLogger(__name__)
SCRAPE_INTERVAL = int(os.getenv("SCRAPE_INTERVAL", "45"))
running = True


def handle_signal(*_):
    global running
    running = False


async def run_cycle():
    logger.info("▶ Scrape cycle started")
    listings = await scrape_all()
    new_count = 0
    deal_count = 0
    watch_count = 0

    update_market_prices(listings)

    for listing in listings:
        d = evaluate(listing)
        if d is None:
            continue
        d = d.to_dict()
        if upsert_deal(d):
            new_count += 1
            if d["is_deal"]:
                deal_count += 1
                logger.info(f"DEAL: {d['title'][:40]} | €{d['price']} | profit €{d['profit']}")
            elif d["is_watch"]:
                watch_count += 1
                logger.info(f"WATCH: {d['title'][:40]} | €{d['price']} | -{d['discount_percent']}%")

    log_scrape(
        total_scraped=len(listings),
        new_found=new_count,
        deals_found=deal_count,
        watch_found=watch_count,
    )
    logger.info(f"✅ Done: {len(listings)} scraped, {new_count} new, {deal_count} deals, {watch_count} watches")

    for deal in get_pending_notifications():
        if deal["is_deal"]:
            success = await send_deal_alert(deal)
        else:
            success = await send_watch_alert(deal)
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
        for _ in range(SCRAPE_INTERVAL):
            if not running:
                break
            await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
