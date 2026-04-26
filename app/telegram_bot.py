"""
Telegram bot — clean alerts, no emoji overload.
"""

import os
import logging
import httpx
from datetime import datetime

logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
BASE_URL  = os.getenv("BASE_URL", "http://localhost:8000")
TG_API    = f"https://api.telegram.org/bot{BOT_TOKEN}"


def fmt_listed(listed_date: str) -> str:
    """Format listed_date to readable string."""
    if not listed_date:
        return ""
    try:
        # Marktplaats returns ISO or epoch
        if listed_date.isdigit():
            dt = datetime.utcfromtimestamp(int(listed_date) / 1000)
        else:
            dt = datetime.fromisoformat(listed_date.replace("Z", ""))
        return dt.strftime("%-d %b %H:%M")
    except Exception:
        return ""


def risk_label(r):
    return {"low": "Low", "medium": "Medium", "high": "High"}.get(r, r)


def liq_label(l):
    return {"high": "High", "medium": "Medium", "low": "Low"}.get(l, l)


def format_deal(deal: dict) -> str:
    title      = deal.get("title", "")[:55]
    price      = deal.get("price", 0)
    market     = deal.get("market_price", 0)
    profit     = deal.get("profit", 0)
    pct        = deal.get("profit_percent", 0)
    disc       = deal.get("discount_percent", 0)
    risk       = deal.get("risk", "")
    liq        = deal.get("liquidity", "")
    loc        = deal.get("location", "NL")
    score      = deal.get("deal_score", 0)
    gpu        = deal.get("gpu", "")
    ram        = deal.get("ram", 0)
    ram_str    = f" · {ram}GB RAM" if ram else ""
    listed     = fmt_listed(deal.get("listed_date", ""))
    listed_str = f" · Опубл. {listed}" if listed else ""

    return (
        f"<b>DEAL — {title}</b>\n\n"
        f"<b>€{price:.0f}</b>  vs ринок €{market:.0f}  (−{disc:.0f}%)\n"
        f"Profit: <b>€{profit:.0f} ({pct:.0f}%)</b>\n\n"
        f"{gpu}{ram_str}\n"
        f"Risk: {risk_label(risk)}  ·  Liquidity: {liq_label(liq)}\n"
        f"📍 {loc}  ·  Score: {score}/100{listed_str}"
    )


def format_watch(deal: dict) -> str:
    title      = deal.get("title", "")[:55]
    price      = deal.get("price", 0)
    market     = deal.get("market_price", 0)
    profit     = deal.get("profit", 0)
    disc       = deal.get("discount_percent", 0)
    risk       = deal.get("risk", "")
    liq        = deal.get("liquidity", "")
    loc        = deal.get("location", "NL")
    gpu        = deal.get("gpu", "")
    listed     = fmt_listed(deal.get("listed_date", ""))
    listed_str = f" · Опубл. {listed}" if listed else ""

    return (
        f"<b>WATCH — {title}</b>\n\n"
        f"<b>€{price:.0f}</b>  vs ринок €{market:.0f}  (−{disc:.0f}%)\n"
        f"Profit: ~€{profit:.0f}\n\n"
        f"{gpu}\n"
        f"Risk: {risk_label(risk)}  ·  Liquidity: {liq_label(liq)}\n"
        f"📍 {loc}{listed_str}"
    )


def build_keyboard(deal: dict) -> dict:
    return {"inline_keyboard": [[
        {"text": "Відкрити оголошення", "url": deal.get("url", "")},
        {"text": "Mini App", "web_app": {"url": f"{BASE_URL}/app"}},
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
        "chat_id": CHAT_ID, "text": format_deal(deal),
        "parse_mode": "HTML", "reply_markup": build_keyboard(deal),
    }, deal.get("image_url", ""))


async def send_watch_alert(deal: dict) -> bool:
    if not BOT_TOKEN or not CHAT_ID:
        return False
    return await _send({
        "chat_id": CHAT_ID, "text": format_watch(deal),
        "parse_mode": "HTML", "reply_markup": build_keyboard(deal),
    }, deal.get("image_url", ""))


async def notify_startup():
    if not BOT_TOKEN or not CHAT_ID:
        return
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            await c.post(f"{TG_API}/sendMessage", json={
                "chat_id": CHAT_ID, "text": "Hunter online", "parse_mode": "HTML",
            })
    except Exception:
        pass
