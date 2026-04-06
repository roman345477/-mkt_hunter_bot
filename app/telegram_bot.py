"""
Telegram bot — deal alerts + watch alerts.
"""

import os
import logging
import httpx

logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
BASE_URL  = os.getenv("BASE_URL", "http://localhost:8000")
TG_API    = f"https://api.telegram.org/bot{BOT_TOKEN}"


def risk_emoji(r): return {"low":"🟢","medium":"🟡","high":"🔴"}.get(r,"⚪")
def liq_emoji(l):  return {"high":"💧💧💧","medium":"💧💧","low":"💧"}.get(l,"💧")


def format_deal(deal: dict) -> str:
    return (
        f"🔥 <b>DEAL</b> — {deal.get('title','')[:50]}\n\n"
        f"💶 <b>€{deal.get('price',0):.0f}</b>  <i>ринок ~€{deal.get('market_price',0):.0f}</i>\n"
        f"💰 Profit: <b>€{deal.get('profit',0):.0f} ({deal.get('profit_percent',0):.0f}%)</b>\n"
        f"⚠️ {risk_emoji(deal.get('risk',''))} {deal.get('risk','').capitalize()}  "
        f"{liq_emoji(deal.get('liquidity',''))} {deal.get('liquidity','').capitalize()}\n"
        f"📍 {deal.get('location','NL')}  ⭐ {deal.get('deal_score',0)}/100"
    )


def format_watch(deal: dict) -> str:
    return (
        f"👀 <b>WATCH</b> — {deal.get('title','')[:50]}\n\n"
        f"💶 <b>€{deal.get('price',0):.0f}</b>  <i>ринок ~€{deal.get('market_price',0):.0f}</i>\n"
        f"📉 Знижка: <b>{deal.get('discount_percent',0):.0f}%</b>  "
        f"Profit: ~€{deal.get('profit',0):.0f}\n"
        f"⚠️ {risk_emoji(deal.get('risk',''))} {deal.get('risk','').capitalize()}  "
        f"{liq_emoji(deal.get('liquidity',''))} {deal.get('liquidity','').capitalize()}\n"
        f"📍 {deal.get('location','NL')}"
    )


def build_keyboard(deal: dict) -> dict:
    return {"inline_keyboard": [[
        {"text": "🔗 Оголошення", "url": deal.get("url", "")},
        {"text": "📱 Mini App", "web_app": {"url": f"{BASE_URL}/app"}},
    ]]}


async def _send(payload: dict, image_url: str = "") -> bool:
    if image_url:
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(f"{TG_API}/sendPhoto", json={
                    **payload, "photo": image_url, "caption": payload["text"]
                })
                if r.status_code == 200:
                    return True
        except Exception:
            pass
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"{TG_API}/sendMessage", json=payload)
            r.raise_for_status()
            return True
    except Exception as e:
        logger.error(f"Telegram error: {e}")
        return False


async def send_deal_alert(deal: dict) -> bool:
    if not BOT_TOKEN or not CHAT_ID:
        return False
    return await _send({
        "chat_id": CHAT_ID,
        "text": format_deal(deal),
        "parse_mode": "HTML",
        "reply_markup": build_keyboard(deal),
    }, deal.get("image_url", ""))


async def send_watch_alert(deal: dict) -> bool:
    if not BOT_TOKEN or not CHAT_ID:
        return False
    return await _send({
        "chat_id": CHAT_ID,
        "text": format_watch(deal),
        "parse_mode": "HTML",
        "reply_markup": build_keyboard(deal),
    }, deal.get("image_url", ""))


async def notify_startup():
    if not BOT_TOKEN or not CHAT_ID:
        return
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            await c.post(f"{TG_API}/sendMessage", json={
                "chat_id": CHAT_ID, "text": "✅ Hunter online", "parse_mode": "HTML",
            })
    except Exception:
        pass
