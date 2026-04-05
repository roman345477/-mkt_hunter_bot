"""
Deal Engine — core logic for evaluating resell opportunity.
Determines profit, risk, and liquidity for each listing.
"""

import re
import logging
from dataclasses import dataclass, asdict
from typing import Optional

logger = logging.getLogger(__name__)

# ── Market prices (realistic Dutch Marktplaats resale range) ──────────────────
MARKET_PRICES = {
    "RTX 4050": {"market": 1000, "resale": 950},
    "RTX 4060": {"market": 1150, "resale": 1100},
}

# ── Liquidity tiers ───────────────────────────────────────────────────────────
HIGH_LIQUIDITY_BRANDS = [
    "asus tuf", "lenovo loq", "hp victus", "msi",
    "acer nitro", "asus rog", "lenovo ideapad gaming",
]

MEDIUM_LIQUIDITY_BRANDS = [
    "dell g15", "acer aspire gaming", "gigabyte",
    "samsung", "razer", "lg", "huawei",
]

# ── Thresholds ────────────────────────────────────────────────────────────────
MIN_DISCOUNT_PCT = 20      # at least 20% below market
MIN_PROFIT_EUR   = 150     # at least €150 profit
MAX_PRICE_EUR    = 1000    # hard filter


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

    # Computed fields
    market_price: float = 0.0
    resale_price: float = 0.0
    profit: float = 0.0
    profit_percent: float = 0.0
    discount_percent: float = 0.0
    risk: str = "high"
    liquidity: str = "low"
    is_deal: bool = False
    deal_score: float = 0.0    # 0–100, higher = better

    def to_dict(self) -> dict:
        return asdict(self)


def evaluate(listing: dict) -> Optional[DealEvaluation]:
    """
    Main evaluation function.
    Returns DealEvaluation if listing passes hard filters, else None.
    """
    # ── Hard filters ──────────────────────────────────────────────────────────
    price = listing.get("price", 0)
    gpu   = listing.get("gpu", "")
    ram   = listing.get("ram", 0)
    condition = listing.get("condition", "")

    if price <= 0 or price > MAX_PRICE_EUR:
        return None
    if gpu not in MARKET_PRICES:
        return None
    if ram and ram < 16:
        return None
    if condition not in ("new", "like_new"):
        return None

    # ── Build evaluation object ───────────────────────────────────────────────
    prices = MARKET_PRICES[gpu]
    market_price = prices["market"]
    resale_price = prices["resale"]

    profit          = resale_price - price
    profit_percent  = round((profit / resale_price) * 100, 1)
    discount_pct    = round(((market_price - price) / market_price) * 100, 1)

    title       = listing.get("title", "")
    description = listing.get("description", "")
    full_text   = (title + " " + description).lower()

    liquidity  = assess_liquidity(full_text)
    risk       = assess_risk(listing, discount_pct)
    is_deal    = (
        discount_pct >= MIN_DISCOUNT_PCT and
        profit >= MIN_PROFIT_EUR
    )
    deal_score = compute_score(profit, discount_pct, liquidity, risk, is_deal)

    return DealEvaluation(
        item_id        = listing["item_id"],
        title          = title,
        price          = price,
        gpu            = gpu,
        ram            = ram,
        condition      = condition,
        location       = listing.get("location", "Netherlands"),
        url            = listing.get("url", ""),
        image_url      = listing.get("image_url", ""),
        seller_name    = listing.get("seller_name", ""),
        description    = description,
        scraped_at     = listing.get("scraped_at", ""),
        market_price   = market_price,
        resale_price   = resale_price,
        profit         = round(profit, 2),
        profit_percent = profit_percent,
        discount_percent = discount_pct,
        risk           = risk,
        liquidity      = liquidity,
        is_deal        = is_deal,
        deal_score     = deal_score,
    )


def assess_liquidity(text: str) -> str:
    for brand in HIGH_LIQUIDITY_BRANDS:
        if brand in text:
            return "high"
    for brand in MEDIUM_LIQUIDITY_BRANDS:
        if brand in text:
            return "medium"
    return "low"


def assess_risk(listing: dict, discount_pct: float) -> str:
    """
    Risk assessment based on:
    - How suspiciously cheap it is
    - Description quality
    - Seller activity
    """
    risk_score = 0

    # Too cheap = suspicious
    if discount_pct > 45:
        risk_score += 3
    elif discount_pct > 35:
        risk_score += 1

    # Short description = less info = more risk
    desc_len = len(listing.get("description", ""))
    if desc_len < 50:
        risk_score += 2
    elif desc_len < 150:
        risk_score += 1

    # New seller
    seller_items = listing.get("seller_items", 0)
    if seller_items == 0:
        risk_score += 2
    elif seller_items < 3:
        risk_score += 1

    # Condition
    if listing.get("condition") == "used":
        risk_score += 1

    if risk_score <= 1:
        return "low"
    elif risk_score <= 3:
        return "medium"
    else:
        return "high"


def compute_score(
    profit: float,
    discount_pct: float,
    liquidity: str,
    risk: str,
    is_deal: bool,
) -> float:
    """Score 0–100. Higher = better deal."""
    if not is_deal:
        return 0.0

    score = 0.0

    # Profit component (max 40 pts)
    score += min(40, profit / 10)

    # Discount component (max 30 pts)
    score += min(30, discount_pct * 0.8)

    # Liquidity bonus
    score += {"high": 20, "medium": 10, "low": 0}[liquidity]

    # Risk penalty
    score -= {"low": 0, "medium": 5, "high": 15}[risk]

    return round(max(0, min(100, score)), 1)
