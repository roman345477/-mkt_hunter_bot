"""
Telegram bot — deal/watch alerts + command handler.
Commands: /deals /watch /status /pause /resume /settings
"""

import os
import logging
import asyncio
import httpx
from datetime import datetime

logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
BASE_URL  = os.getenv("BASE_URL", "http://localhost:8000")
TG_API    = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Pause flag — set by /pause command
is_paused = False
_last_update_id = 0


# ── Formatters ────────────────────────────────────────────────────────────────

def fmt_listed(raw: str) -> str:
    if not raw: return ""
    try:
        s = str(raw).strip()
        if s.isdigit():
            n = int(s)
            dt = datetime.utcfromtimestamp(n/1000 if n > 1e10 else n)
        else:
            dt = datetime.fromisoformat(s.replace("Z","").split("+")[0][:19])
        return dt.strftime("%-d %b %H:%M")
    except Exception:
        return ""


def is_fresh(listed_date: str) -> bool:
    if not listed_date: return False
    try:
        s = str(listed_date).strip()
        if s.isdigit():
            n = int(s)
            dt = datetime.utcfromtimestamp(n/1000 if n > 1e10 else n)
        else:
            dt = datetime.fromisoformat(s.replace("Z","").split("+")[0][:19])
        return (datetime.utcnow() - dt).total_seconds() < 1800
    except Exception:
        return False


def specs_line(d: dict) -> str:
    p = []
    if d.get("ram"):     p.append(f"{d['ram']}GB RAM")
    if d.get("storage"): p.append(f"{d['storage']}GB SSD")
    if d.get("screen"):  p.append(f'{d["screen"]}"')
    if d.get("cpu"):     p.append(d["cpu"])
    return "  ·  ".join(p)


def risk_label(r): return {"low":"Low ✓","medium":"Medium","high":"High !"}.get(r, r)
def liq_label(l):  return {"high":"High","medium":"Medium","low":"Low"}.get(l, l)


def format_deal(d: dict) -> str:
    specs  = specs_line(d)
    listed = fmt_listed(d.get("listed_date",""))
    fresh  = is_fresh(d.get("listed_date",""))
    header = f"{'🔥 НОВЕ ' if fresh else ''}DEAL — {d.get('title','')[:55]}"
    return (
        f"<b>{header}</b>\n\n"
        f"<b>€{d.get('price',0):.0f}</b>  vs ринок €{d.get('market_price',0):.0f}  (−{d.get('discount_percent',0):.0f}%)\n"
        f"Profit: <b>€{d.get('profit',0):.0f} ({d.get('profit_percent',0):.0f}%)</b>\n\n"
        f"{d.get('gpu','')}{'  ·  '+specs if specs else ''}\n"
        f"Risk: {risk_label(d.get('risk',''))}  ·  Liquidity: {liq_label(d.get('liquidity',''))}\n"
        f"📍 {d.get('location','NL')}  ·  Score: {d.get('deal_score',0)}/100"
        + (f"\nОпубл. {listed}" if listed else "")
    )


def format_watch(d: dict) -> str:
    specs  = specs_line(d)
    listed = fmt_listed(d.get("listed_date",""))
    return (
        f"<b>WATCH — {d.get('title','')[:55]}</b>\n\n"
        f"<b>€{d.get('price',0):.0f}</b>  vs ринок €{d.get('market_price',0):.0f}  (−{d.get('discount_percent',0):.0f}%)\n"
        f"Profit: ~€{d.get('profit',0):.0f}\n\n"
        f"{d.get('gpu','')}{'  ·  '+specs if specs else ''}\n"
        f"📍 {d.get('location','NL')}"
        + (f"\nОпубл. {listed}" if listed else "")
    )


def format_price_drop(d: dict) -> str:
    old   = d.get("price_dropped_from", 0)
    curr  = d.get("price", 0)
    drop  = d.get("price_drop_pct", 0)
    specs = specs_line(d)
    return (
        f"<b>ЦІНА ЗНИЖЕНА — {d.get('title','')[:50]}</b>\n\n"
        f"<s>€{old:.0f}</s>  →  <b>€{curr:.0f}</b>  (−{drop:.0f}%)\n"
        f"Profit тепер: <b>€{d.get('profit',0):.0f}</b>\n\n"
        f"{d.get('gpu','')}{'  ·  '+specs if specs else ''}\n"
        f"📍 {d.get('location','NL')}"
    )


def format_deal_short(d: dict, i: int) -> str:
    """Compact format for list commands."""
    return (
        f"{i}. <b>{d.get('title','')[:45]}</b>\n"
        f"   €{d.get('price',0):.0f}  →  profit €{d.get('profit',0):.0f} ({d.get('profit_percent',0):.0f}%)"
        f"  ·  {d.get('gpu','')}\n"
        f"   <a href=\"{d.get('url','')}\">Відкрити</a>"
    )


def build_keyboard(deal: dict) -> dict:
    return {"inline_keyboard": [[
        {"text": "Відкрити оголошення", "url": deal.get("url","")},
        {"text": "Mini App", "web_app": {"url": f"{BASE_URL}/app"}},
    ]]}


# ── Send helpers ──────────────────────────────────────────────────────────────

async def _send(payload: dict, image_url: str = "") -> bool:
    if image_url:
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(f"{TG_API}/sendPhoto",
                    json={**payload, "photo": image_url, "caption": payload["text"]})
                if r.status_code == 200: return True
        except Exception:
            pass
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"{TG_API}/sendMessage", json=payload)
            r.raise_for_status()
            return True
    except Exception as e:
        logger.error(f"TG error: {e}")
        return False


async def send_text(text: str, chat_id: str = "") -> bool:
    cid = chat_id or CHAT_ID
    if not BOT_TOKEN or not cid: return False
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"{TG_API}/sendMessage", json={
                "chat_id": cid, "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            })
            r.raise_for_status()
            return True
    except Exception as e:
        logger.error(f"send_text error: {e}")
        return False


async def send_deal_alert(d: dict) -> bool:
    if not BOT_TOKEN or not CHAT_ID: return False
    if is_paused: return False
    return await _send({
        "chat_id": CHAT_ID, "text": format_deal(d),
        "parse_mode": "HTML", "reply_markup": build_keyboard(d),
    }, d.get("image_url",""))


async def send_watch_alert(d: dict) -> bool:
    if not BOT_TOKEN or not CHAT_ID: return False
    if is_paused: return False
    return await _send({
        "chat_id": CHAT_ID, "text": format_watch(d),
        "parse_mode": "HTML", "reply_markup": build_keyboard(d),
    }, d.get("image_url",""))


async def send_price_drop_alert(d: dict) -> bool:
    if not BOT_TOKEN or not CHAT_ID: return False
    if is_paused: return False
    return await _send({
        "chat_id": CHAT_ID, "text": format_price_drop(d),
        "parse_mode": "HTML", "reply_markup": build_keyboard(d),
    }, d.get("image_url",""))


async def notify_startup():
    if not BOT_TOKEN or not CHAT_ID: return
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            await c.post(f"{TG_API}/sendMessage", json={
                "chat_id": CHAT_ID, "text": "Hunter online", "parse_mode": "HTML",
            })
    except Exception:
        pass


# ── Command handler ───────────────────────────────────────────────────────────

async def handle_command(text: str, chat_id: str):
    """Process incoming Telegram command."""
    global is_paused

    cmd = text.strip().lower().split()[0].replace("@", "")

    if cmd == "/deals" or cmd == "/start":
        from database import get_deals
        deals = get_deals(only_deals=True, only_active=True, limit=5, sort_by="score")
        if not deals:
            await send_text("Наразі немає активних угод. Система сканує...", chat_id)
            return
        lines = [f"<b>Топ {len(deals)} угод зараз:</b>\n"]
        for i, d in enumerate(deals, 1):
            lines.append(format_deal_short(d, i))
        lines.append(f"\n<a href=\"{BASE_URL}/app\">Відкрити Mini App</a>")
        await send_text("\n".join(lines), chat_id)

    elif cmd == "/watch":
        from database import get_deals
        watches = get_deals(only_deals=False, include_watch=True, only_active=True, limit=5, sort_by="score")
        watches = [w for w in watches if w.get("is_watch") and not w.get("is_deal")]
        if not watches:
            await send_text("Немає watch оголошень.", chat_id)
            return
        lines = [f"<b>Watch список ({len(watches)}):</b>\n"]
        for i, d in enumerate(watches, 1):
            lines.append(
                f"{i}. <b>{d.get('title','')[:45]}</b>\n"
                f"   €{d.get('price',0):.0f}  −{d.get('discount_percent',0):.0f}%"
                f"  ·  {d.get('gpu','')}\n"
                f"   <a href=\"{d.get('url','')}\">Відкрити</a>"
            )
        await send_text("\n".join(lines), chat_id)

    elif cmd == "/status":
        from database import get_stats, get_scrape_stats
        stats = get_stats()
        logs  = get_scrape_stats()
        last  = logs[0] if logs else {}
        last_time = last.get("scraped_at","—")
        try:
            dt = datetime.fromisoformat(last_time)
            mins_ago = int((datetime.utcnow() - dt).total_seconds() / 60)
            last_str = f"{mins_ago} хв тому"
        except Exception:
            last_str = last_time

        pause_str = "⏸ ПРИЗУПИНЕНО" if is_paused else "▶ Активний"
        await send_text(
            f"<b>Статус Hunter</b>\n\n"
            f"Стан: {pause_str}\n"
            f"Останній скрап: {last_str}\n"
            f"Знайдено оголошень: {stats.get('total',0)}\n"
            f"Активних угод: {stats.get('deals',0)}\n"
            f"Watch: {stats.get('watches',0)}\n"
            f"Продано/знято: {stats.get('sold',0)}\n"
            f"Найкращий profit: €{stats.get('best_profit') or 0:.0f}",
            chat_id
        )

    elif cmd == "/pause":
        is_paused = True
        await send_text("⏸ Сканування призупинено. /resume щоб відновити.", chat_id)

    elif cmd == "/resume":
        is_paused = False
        await send_text("▶ Сканування відновлено.", chat_id)

    elif cmd == "/settings":
        import deal_engine as de
        gpus = de.ALLOWED_GPUS if de.ALLOWED_GPUS else "Всі"
        gpus_str = ", ".join(gpus) if isinstance(gpus, list) else gpus
        await send_text(
            f"<b>Поточні налаштування</b>\n\n"
            f"GPU: {gpus_str}\n"
            f"Мін. знижка (Deal): {de.MIN_DISCOUNT_PCT}%\n"
            f"Мін. знижка (Watch): {de.WATCH_DISCOUNT_PCT}%\n"
            f"Мін. profit: €{de.MIN_PROFIT_EUR:.0f}\n"
            f"Ціна: €{de.MIN_PRICE_EUR:.0f} – €{de.MAX_PRICE_EUR:.0f}\n"
            f"Мін. RAM: {de.MIN_RAM}GB\n\n"
            f"Змінити: {BASE_URL}/app → Налаштування",
            chat_id
        )

    elif cmd == "/help":
        await send_text(
            "<b>Команди Hunter</b>\n\n"
            "/deals — топ 5 угод зараз\n"
            "/watch — watch список\n"
            "/status — статистика системи\n"
            "/pause — призупинити сповіщення\n"
            "/resume — відновити сповіщення\n"
            "/settings — поточні налаштування\n"
            "/help — ця довідка",
            chat_id
        )

    else:
        await send_text(
            "Невідома команда. Напиши /help для списку команд.",
            chat_id
        )


# ── Polling loop ──────────────────────────────────────────────────────────────

async def poll_updates():
    """Long-poll Telegram for incoming messages/commands."""
    global _last_update_id

    if not BOT_TOKEN:
        return

    try:
        async with httpx.AsyncClient(timeout=35) as c:
            r = await c.get(f"{TG_API}/getUpdates", params={
                "offset": _last_update_id + 1,
                "timeout": 30,
                "allowed_updates": ["message"],
            })
            if r.status_code != 200:
                return
            updates = r.json().get("result", [])

        for upd in updates:
            _last_update_id = upd["update_id"]
            msg = upd.get("message", {})
            text = msg.get("text", "")
            chat_id = str(msg.get("chat", {}).get("id", ""))

            # Only accept from authorized chat
            if chat_id and text.startswith("/"):
                logger.info(f"Command from {chat_id}: {text}")
                try:
                    await handle_command(text, chat_id)
                except Exception as e:
                    logger.error(f"Command error: {e}")

    except Exception as e:
        logger.debug(f"Poll error: {e}")


async def start_polling():
    """Run polling loop forever."""
    logger.info("Telegram polling started")
    while True:
        try:
            await poll_updates()
        except Exception as e:
            logger.debug(f"Polling loop error: {e}")
        await asyncio.sleep(1)
