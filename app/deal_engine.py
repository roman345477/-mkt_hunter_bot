"""
Deal Engine — dynamic market prices + profit/risk/liquidity evaluation.
"""

import re
import logging
import statistics
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

MARKET_PRICES_DEFAULT = {
    "RTX 4050": {"market": 1000, "resale": 950},
    "RTX 4060": {"market": 1150, "resale": 1100},
}

_price_cache: dict = {}
_CACHE_TTL_HOURS = 6

HIGH_LIQUIDITY_BRANDS = [
    "asus tuf", "lenovo loq", "hp victus", "msi",
    "acer nitro", "asus rog", "lenovo ideapad gaming",
]
MEDIUM_LIQUIDITY_BRANDS = [
    "dell g15", "acer aspire gaming", "gigabyte",
    "samsung", "razer", "lg", "huawei",
]

MIN_DISCOUNT_PCT  = 15    # знижено з 20% до 15%
WATCH_DISCOUNT_PCT = 10   # "майже угода" — для WATCH алертів
MIN_PROFIT_EUR    = 100   # знижено з 150 до 100
MAX_PRICE_EUR     = 1000


def update_market_prices(all_listings: list):
    now = datetime.utcnow()
    for gpu in ["RTX 4050", "RTX 4060"]:
        cached = _price_cache.get(gpu)
        if cached and (now - cached["updated"]) < timedelta(hours=_CACHE_TTL_HOURS):
            continue
        prices = [
            l["price"] for l in all_listings
            if l.get("gpu") == gpu and 400 <= l.get("price", 0) <= 1400
        ]
        if len(prices) < 5:
            logger.info(f"Not enough data for {gpu} ({len(prices)} samples), using default")
            continue
        median_price = statistics.median(prices)
        market = round(median_price * 1.05)
        resale = round(median_price * 0.98)
        _price_cache[gpu] = {
            "market": market, "resale": resale, "updated": now,
            "sample_size": len(prices), "median_raw": round(median_price),
        }
        logger.info(f"📊 {gpu}: market=€{market} resale=€{resale} (n={len(prices)}, median=€{round(median_price)})")


def get_market_prices(gpu: str) -> dict:
    if gpu in _price_cache:
        return _price_cache[gpu]
    return MARKET_PRICES_DEFAULT.get(gpu, {"market": 1000, "resale": 950})


def get_price_cache_info() -> dict:
    result = {}
    for gpu, data in _price_cache.items():
        result[gpu] = {
            "market": data["market"], "resale": data["resale"],
            "sample_size": data.get("sample_size", 0),
            "updated": data["updated"].isoformat(), "source": "dynamic",
        }
    for gpu, data in MARKET_PRICES_DEFAULT.items():
        if gpu not in result:
            result[gpu] = {**data, "source": "default", "sample_size": 0}
    return result


@dataclass
class DealEvaluation:
    item_id: str
    title: str
    price: float
    gpu: str
    ram: int
    condition: str
    location: str
    url: str
    image_url: str
    seller_name: str
    description: str
    scraped_at: str
    market_price: float = 0.0
    resale_price: float = 0.0
    profit: float = 0.0
    profit_percent: float = 0.0
    discount_percent: float = 0.0
    risk: str = "high"
    liquidity: str = "low"
    is_deal: bool = False
    is_watch: bool = False   # нове поле — "майже угода"
    deal_score: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def evaluate(listing: dict) -> Optional[DealEvaluation]:
    price     = listing.get("price", 0)
    gpu       = listing.get("gpu", "")
    ram       = listing.get("ram", 0)
    condition = listing.get("condition", "")

    if price <= 0 or price > MAX_PRICE_EUR:
        logger.info(f"SKIP price: {listing.get('title','')[:30]} price={price}")
        return None
    if gpu not in MARKET_PRICES_DEFAULT:
        logger.info(f"SKIP gpu: {listing.get('title','')[:30]} gpu='{gpu}'")
        return None
    if ram and ram < 16:
        logger.info(f"SKIP ram: {listing.get('title','')[:30]} ram={ram}")
        return None
    if condition not in ("new", "like_new"):
        logger.info(f"SKIP condition: {listing.get('title','')[:30]} condition='{condition}'")
        return None

    prices       = get_market_prices(gpu)
    market_price = prices["market"]
    resale_price = prices["resale"]

    profit         = resale_price - price
    profit_percent = round((profit / resale_price) * 100, 1)
    discount_pct   = round(((market_price - price) / market_price) * 100, 1)

    title     = listing.get("title", "")
    desc      = listing.get("description", "")
    full_text = (title + " " + desc).lower()

    liquidity  = assess_liquidity(full_text)
    risk       = assess_risk(listing, discount_pct)
    is_deal    = discount_pct >= MIN_DISCOUNT_PCT and profit >= MIN_PROFIT_EUR
    is_watch   = (not is_deal) and discount_pct >= WATCH_DISCOUNT_PCT and profit >= 50
    deal_score = compute_score(profit, discount_pct, liquidity, risk, is_deal)

    return DealEvaluation(
        item_id=listing["item_id"], title=title, price=price,
        gpu=gpu, ram=ram, condition=condition,
        location=listing.get("location", "Netherlands"),
        url=listing.get("url", ""), image_url=listing.get("image_url", ""),
        seller_name=listing.get("seller_name", ""), description=desc,
        scraped_at=listing.get("scraped_at", ""),
        market_price=market_price, resale_price=resale_price,
        profit=round(profit, 2), profit_percent=profit_percent,
        discount_percent=discount_pct, risk=risk, liquidity=liquidity,
        is_deal=is_deal, is_watch=is_watch, deal_score=deal_score,
    )


def assess_liquidity(text: str) -> str:
    for b in HIGH_LIQUIDITY_BRANDS:
        if b in text: return "high"
    for b in MEDIUM_LIQUIDITY_BRANDS:
        if b in text: return "medium"
    return "low"


def assess_risk(listing: dict, discount_pct: float) -> str:
    score = 0
    if discount_pct > 45: score += 3
    elif discount_pct > 35: score += 1
    desc_len = len(listing.get("description", ""))
    if desc_len < 50: score += 2
    elif desc_len < 150: score += 1
    items = listing.get("seller_items", 0)
    if items == 0: score += 2
    elif items < 3: score += 1
    if listing.get("condition") == "used": score += 1
    if score <= 1: return "low"
    elif score <= 3: return "medium"
    return "high"


def compute_score(profit, discount_pct, liquidity, risk, is_deal) -> float:
    if not is_deal: return 0.0
    s = min(40, profit / 10) + min(30, discount_pct * 0.8)
    s += {"high": 20, "medium": 10, "low": 0}[liquidity]
    s -= {"low": 0, "medium": 5, "high": 15}[risk]
    return round(max(0, min(100, s)), 1)
