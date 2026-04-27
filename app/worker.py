"""Worker — scrape, evaluate, notify, cleanup."""

import asyncio, logging, os, signal
from scraper import scrape_all
from deal_engine import evaluate
from database import init_db, upsert_deal, get_pending_notifications, mark_notified, log_scrape, cleanup_old_records
from telegram_bot import send_deal_alert, send_watch_alert, notify_startup
import market_prices as mp
import deal_engine as de

logger = logging.getLogger(__name__)
SCRAPE_INTERVAL = int(os.getenv("SCRAPE_INTERVAL", "90"))
running = True
_cycle = 0

def handle_signal(*_):
    global running; running = False

async def run_cycle():
    global _cycle; _cycle += 1
    logger.info("▶ Cycle start")
    listings = await scrape_all(max_price=int(de.MAX_PRICE_EUR))
    if not listings:
        log_scrape(0,0,0,0); return

    mp.update_from_listings(listings)

    new_c = deal_c = watch_c = 0
    for l in listings:
        d = evaluate(l)
        if d is None: continue
        d = d.to_dict()
        if upsert_deal(d):
            new_c += 1
            if d["is_deal"]:
                deal_c += 1
                logger.info(f"DEAL: {d['title'][:40]} €{d['price']} profit €{d['profit']}")
            elif d["is_watch"]:
                watch_c += 1
                logger.info(f"WATCH: {d['title'][:40]} €{d['price']} -{d['discount_percent']}%")

    log_scrape(len(listings), new_c, deal_c, watch_c)
    logger.info(f"Done: {len(listings)} scraped, {new_c} new, {deal_c} deals, {watch_c} watches")

    for deal in get_pending_notifications():
        ok = await send_deal_alert(deal) if deal["is_deal"] else await send_watch_alert(deal)
        if ok: mark_notified(deal["item_id"])
        await asyncio.sleep(0.5)

    if _cycle % 100 == 0:
        cleanup_old_records()

async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    init_db()
    await notify_startup()
    logger.info(f"Worker started — interval {SCRAPE_INTERVAL}s")
    while running:
        try:
            await run_cycle()
        except Exception as e:
            logger.error(f"Cycle error: {e}", exc_info=True)
        for _ in range(SCRAPE_INTERVAL):
            if not running: break
            await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
