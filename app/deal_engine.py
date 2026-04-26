"""
Deal Engine — dynamic p75 pricing, configurable filters.
"""

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

# Configurable via /settings endpoint
MIN_DISCOUNT_PCT   = 15
WATCH_DISCOUNT_PCT = 10
MIN_PROFIT_EUR     = 100
MAX_PRICE_EUR      = 1000
MIN_RAM            = 16
MIN_DESC_LEN       = 30
ALLOWED_GPUS       = ["RTX 4050", "RTX 4060"]


def percentile(data: list, p: float) -> float:
    if not data: return 0
    s = sorted(data)
    k = (len(s) - 1) * p / 100
    f = int(k)
    c = f + 1
    if c >= len(s): return s[f]
    return s[f] + (k - f) * (s[c] - s[f])


def update_market_prices(all_listings: list):
    now = datetime.utcnow()
    for gpu in ALLOWED_GPUS:
        cached = _price_cache.get(gpu)
        if cached and (now - cached["updated"]) < timedelta(hours=_CACHE_TTL_HOURS):
            continue
        prices = [
            l["price"] for l in all_listings
            if l.get("gpu") == gpu and 400 <= l.get("price", 0) <= 1400
        ]
        if len(prices) < 5:
            continue
        p75    = percentile(prices, 75)
        market = round(p75)
        resale = round(p75 * 0.93)
        _price_cache[gpu] = {
            "market": market, "resale": resale, "updated": now,
            "sample_size": len(prices),
            "median_raw": round(statistics.median(prices)),
            "p75": round(p75),
        }
        logger.info(
            f"📊 {gpu}: market=€{market} resale=€{resale} "
            f"(n={len(prices)}, median=€{round(statistics.median(prices))}, p75=€{round(p75)})"
        )


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
            "updated": data["updated"].isoformat(),
            "source": "dynamic", "p75": data.get("p75", 0),
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
    listed_date: str
    market_price: float = 0.0
    resale_price: float = 0.0
    profit: float = 0.0
    profit_percent: float = 0.0
    discount_percent: float = 0.0
    risk: str = "high"
    liquidity: str = "low"
    is_deal: bool = False
    is_watch: bool = False
    deal_score: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def evaluate(listing: dict) -> Optional[DealEvaluation]:
    price     = listing.get("price", 0)
    gpu       = listing.get("gpu", "")
    ram       = listing.get("ram", 0)
    condition = listing.get("condition", "")
    desc      = listing.get("description", "") or ""
    title     = listing.get("title", "") or ""

    if price <= 0 or price > MAX_PRICE_EUR:
        return None
    if gpu not in ALLOWED_GPUS:
        return None
    if ram and MIN_RAM and ram < MIN_RAM:
        return None
    if condition not in ("new", "like_new"):
        return None
    if len(desc) < MIN_DESC_LEN and len(title) < 20:
        return None

    prices       = get_market_prices(gpu)
    market_price = prices["market"]
    resale_price = prices["resale"]

    profit         = resale_price - price
    profit_percent = round((profit / resale_price) * 100, 1)
    discount_pct   = round(((market_price - price) / market_price) * 100, 1)

    full_text  = (title + " " + desc).lower()
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
        listed_date=listing.get("listed_date", ""),
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
    desc_len = len(listing.get("description", "") or "")
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
