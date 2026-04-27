"""
Telegram bot — clean alerts with full specs and listed date.
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


def fmt_listed(raw: str) -> str:
    if not raw: return ""
    try:
        dt = datetime.utcfromtimestamp(int(raw)/1000) if raw.isdigit() else datetime.fromisoformat(raw.replace("Z",""))
        return dt.strftime("%-d %b %H:%M")
    except Exception:
        return ""


def specs_line(deal: dict) -> str:
    parts = []
    if deal.get("ram"):    parts.append(f"{deal['ram']}GB RAM")
    if deal.get("storage"): parts.append(f"{deal['storage']}GB SSD")
    if deal.get("screen"): parts.append(f'{deal["screen"]}"')
    if deal.get("cpu"):    parts.append(deal["cpu"])
    return "  ·  ".join(parts) if parts else ""


def format_deal(d: dict) -> str:
    specs   = specs_line(d)
    listed  = fmt_listed(d.get("listed_date",""))
    risk_m  = {"low":"Low ✓","medium":"Medium","high":"High !"}.get(d.get("risk",""),"")
    liq_m   = {"high":"High","medium":"Medium","low":"Low"}.get(d.get("liquidity",""),"")
    return (
        f"<b>DEAL — {d.get('title','')[:55]}</b>\n\n"
        f"<b>€{d.get('price',0):.0f}</b>  vs ринок €{d.get('market_price',0):.0f}  (−{d.get('discount_percent',0):.0f}%)\n"
        f"Profit: <b>€{d.get('profit',0):.0f} ({d.get('profit_percent',0):.0f}%)</b>\n\n"
        f"{d.get('gpu','')}{'  ·  '+specs if specs else ''}\n"
        f"Risk: {risk_m}  ·  Liquidity: {liq_m}\n"
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


def build_keyboard(deal: dict) -> dict:
    return {"inline_keyboard": [[
        {"text": "Відкрити оголошення", "url": deal.get("url","")},
        {"text": "Mini App", "web_app": {"url": f"{BASE_URL}/app"}},
    ]]}


async def _send(payload: dict, image_url: str = "") -> bool:
    if image_url:
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(f"{TG_API}/sendPhoto", json={**payload,"photo":image_url,"caption":payload["text"]})
                if r.status_code == 200: return True
        except Exception: pass
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"{TG_API}/sendMessage", json=payload)
            r.raise_for_status(); return True
    except Exception as e:
        logger.error(f"TG error: {e}"); return False


async def send_deal_alert(d: dict) -> bool:
    if not BOT_TOKEN or not CHAT_ID: return False
    return await _send({"chat_id":CHAT_ID,"text":format_deal(d),"parse_mode":"HTML","reply_markup":build_keyboard(d)},d.get("image_url",""))

async def send_watch_alert(d: dict) -> bool:
    if not BOT_TOKEN or not CHAT_ID: return False
    return await _send({"chat_id":CHAT_ID,"text":format_watch(d),"parse_mode":"HTML","reply_markup":build_keyboard(d)},d.get("image_url",""))

async def notify_startup():
    if not BOT_TOKEN or not CHAT_ID: return
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            await c.post(f"{TG_API}/sendMessage",json={"chat_id":CHAT_ID,"text":"Hunter online","parse_mode":"HTML"})
    except Exception: pass
