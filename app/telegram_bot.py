"""
Telegram bot — sends deal alerts with inline buttons.
"""

import os
import logging
import httpx
from typing import Optional

logger = logging.getLogger(__name__)

BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID", "")
BASE_URL   = os.getenv("BASE_URL", "http://localhost:8000")

TG_API     = f"https://api.telegram.org/bot{BOT_TOKEN}"


def risk_emoji(risk: str) -> str:
    return {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(risk, "⚪")


def liquidity_emoji(liq: str) -> str:
    return {"high": "💧💧💧", "medium": "💧💧", "low": "💧"}.get(liq, "💧")


def format_deal_message(deal: dict) -> str:
    gpu        = deal.get("gpu", "")
    title      = deal.get("title", "Unknown")[:60]
    price      = deal.get("price", 0)
    profit     = deal.get("profit", 0)
    profit_pct = deal.get("profit_percent", 0)
    risk       = deal.get("risk", "medium")
    liquidity  = deal.get("liquidity", "medium")
    location   = deal.get("location", "NL")
    market     = deal.get("market_price", 0)
    score      = deal.get("deal_score", 0)

    return (
        f"🔥 <b>DEAL FOUND</b>\n\n"
        f"📦 <b>Model:</b> {title}\n"
        f"🎮 <b>GPU:</b> {gpu}\n"
        f"💶 <b>Price:</b> €{price:.0f} <i>(market ~€{market:.0f})</i>\n"
        f"💰 <b>Profit:</b> €{profit:.0f} ({profit_pct:.0f}%)\n"
        f"⚠️ <b>Risk:</b> {risk_emoji(risk)} {risk.capitalize()}\n"
        f"💧 <b>Liquidity:</b> {liquidity_emoji(liquidity)} {liquidity.capitalize()}\n"
        f"📍 <b>Location:</b> {location}\n"
        f"⭐ <b>Score:</b> {score}/100"
    )


def build_keyboard(deal: dict) -> dict:
    item_id = deal.get("item_id", "")
    url     = deal.get("url", "")
    app_url = f"{BASE_URL}/app?deal={item_id}"

    return {
        "inline_keyboard": [[
            {"text": "🔗 Відкрити оголошення", "url": url},
            {"text": "📱 Mini App", "web_app": {"url": app_url}},
        ]]
    }


async def send_deal_alert(deal: dict) -> bool:
    if not BOT_TOKEN or not CHAT_ID:
        logger.warning("Telegram not configured (BOT_TOKEN or CHAT_ID missing)")
        return False

    text     = format_deal_message(deal)
    keyboard = build_keyboard(deal)

    payload: dict = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": keyboard,
        "disable_web_page_preview": False,
    }

    # If image available, send as photo
    image_url = deal.get("image_url", "")
    if image_url:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(
                    f"{TG_API}/sendPhoto",
                    json={**payload, "photo": image_url, "caption": text},
                )
                if r.status_code == 200:
                    return True
        except Exception:
            pass  # fallback to text

    # Plain text fallback
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{TG_API}/sendMessage", json=payload)
            r.raise_for_status()
            return True
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")
        return False


async def send_batch_alerts(deals: list[dict]) -> int:
    """Send multiple alerts; returns count of successful sends."""
    import asyncio
    sent = 0
    for deal in deals:
        success = await send_deal_alert(deal)
        if success:
            sent += 1
        await asyncio.sleep(0.5)    # rate limit
    return sent


async def notify_startup():
    if not BOT_TOKEN or not CHAT_ID:
        return
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(f"{TG_API}/sendMessage", json={
                "chat_id": CHAT_ID,
                "text": "🚀 <b>Marktplaats Hunter запущено!</b>\nСканую RTX 4050/4060 ноутбуки...",
                "parse_mode": "HTML",
            })
    except Exception:
        pass
