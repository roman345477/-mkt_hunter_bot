"""
Deal Engine — configurable filters, all GPU support.
ALLOWED_GPUS = None means ALL gpus allowed.
ALLOWED_GPUS = ["RTX 4060"] means ONLY that GPU.
"""

import logging
from dataclasses import dataclass, asdict
from typing import Optional, List
import market_prices as mp

logger = logging.getLogger(__name__)

HIGH_LIQUIDITY_BRANDS = [
    "asus tuf", "lenovo loq", "hp victus", "msi cyborg",
    "acer nitro", "asus rog", "lenovo ideapad gaming", "dell g15",
]
MEDIUM_LIQUIDITY_BRANDS = [
    "acer aspire gaming", "gigabyte", "samsung", "razer",
    "hp omen", "msi katana", "msi thin",
]

# ── Configurable settings ─────────────────────────────────────────────────────
MIN_DISCOUNT_PCT   = 15.0
WATCH_DISCOUNT_PCT = 10.0
MIN_PROFIT_EUR     = 100.0
MAX_PRICE_EUR      = 5000.0
MIN_PRICE_EUR      = 0.0
MIN_RAM            = 16
MIN_STORAGE        = 0
MIN_SCREEN         = 0.0
MAX_SCREEN         = 0.0
# None = all GPUs allowed; list = only these GPUs
ALLOWED_GPUS: Optional[List[str]] = None
ALLOWED_CPUS: List[str] = []
MIN_DESC_LEN = 30


@dataclass
class DealEvaluation:
    item_id: str
    title: str
    price: float
    gpu: str
    ram: int
    storage: int
    screen: float
    cpu: str
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
    price   = listing.get("price", 0)
    gpu     = listing.get("gpu", "")
    ram     = listing.get("ram", 0)
    storage = listing.get("storage", 0)
    screen  = listing.get("screen", 0.0)
    cpu     = listing.get("cpu", "")
    cond    = listing.get("condition", "")
    desc    = listing.get("description", "") or ""
    title   = listing.get("title", "") or ""

    # Price filter
    if price <= MIN_PRICE_EUR or price > MAX_PRICE_EUR:
        return None

    # GPU filter — None means all allowed
    if ALLOWED_GPUS is not None and gpu not in ALLOWED_GPUS:
        return None

    # GPU must be in known list
    if gpu not in mp.known_gpus():
        return None

    # RAM filter
    if ram and MIN_RAM and ram < MIN_RAM:
        return None

    # Storage filter
    if storage and MIN_STORAGE and storage < MIN_STORAGE:
        return None

    # Screen filter
    if screen and MIN_SCREEN and screen < MIN_SCREEN:
        return None
    if screen and MAX_SCREEN and screen > MAX_SCREEN:
        return None

    # CPU filter — empty = all
    if ALLOWED_CPUS and cpu and cpu not in ALLOWED_CPUS:
        return None

    # Condition
    if cond not in ("new", "like_new"):
        return None

    # Minimum description
    if len(desc) < MIN_DESC_LEN and len(title) < 20:
        return None

    prices       = mp.get(gpu)
    market_price = prices["market"]
    resale_price = prices["resale"]

    profit         = resale_price - price
    profit_percent = round((profit / max(resale_price, 1)) * 100, 1)
    discount_pct   = round(((market_price - price) / max(market_price, 1)) * 100, 1)

    full_text  = (title + " " + desc).lower()
    liquidity  = assess_liquidity(full_text)
    risk       = assess_risk(listing, discount_pct)
    is_deal    = discount_pct >= MIN_DISCOUNT_PCT and profit >= MIN_PROFIT_EUR
    is_watch   = (not is_deal) and discount_pct >= WATCH_DISCOUNT_PCT and profit >= 50
    deal_score = compute_score(profit, discount_pct, liquidity, risk, is_deal)

    return DealEvaluation(
        item_id=listing["item_id"], title=title, price=price,
        gpu=gpu, ram=ram, storage=storage, screen=screen, cpu=cpu,
        condition=cond,
        location=listing.get("location", "Netherlands"),
        url=listing.get("url", ""),
        image_url=listing.get("image_url", ""),
        seller_name=listing.get("seller_name", ""),
        description=desc,
        scraped_at=listing.get("scraped_at", ""),
        listed_date=listing.get("listed_date", ""),
        market_price=market_price, resale_price=resale_price,
        profit=round(profit, 2), profit_percent=profit_percent,
        discount_percent=discount_pct,
        risk=risk, liquidity=liquidity,
        is_deal=is_deal, is_watch=is_watch, deal_score=deal_score,
    )


def assess_liquidity(text: str) -> str:
    for b in HIGH_LIQUIDITY_BRANDS:
        if b in text: return "high"
    for b in MEDIUM_LIQUIDITY_BRANDS:
        if b in text: return "medium"
    return "low"


BUNDLE_KEYWORDS = [
    "+ headset", "+ mouse", "+ muis", "+ bag", "+ tas", "+ keyboard",
    "+ toetsenbord", "+ charger", "+ adapter", "+ dock", "+ sleeve",
    "+ logitech", "+ razer", "+ steelseries", "+ hyperx", "+ corsair",
    "met headset", "met muis", "met tas", "met toetsenbord",
    "met logitech", "met razer", "met accessoires",
    "incl headset", "incl muis", "incl tas", "incl accessoires",
    "& headset", "& mouse", "& bag",
    "inclusief muis", "inclusief tas", "inclusief headset",
]

# Regex patterns for bundles like "+ something" or "met iets"
import re as _re
_BUNDLE_PATTERNS = [
    r'\+\s+\w+set',       # + headset, + dataset etc
    r'\+\s+\w+muis',      # + muis
    r'met\s+\w+set',    # met headset
    r'incl\.?\s+\w+set',  # incl headset
]


def is_bundle(listing: dict) -> bool:
    """Returns True if listing includes extra items that inflate price."""
    text = ((listing.get("title","") or "") + " " + (listing.get("description","") or "")).lower()
    if any(kw in text for kw in BUNDLE_KEYWORDS):
        return True
    for pat in _BUNDLE_PATTERNS:
        if _re.search(pat, text):
            return True
    return False


def assess_risk(listing: dict, discount_pct: float) -> str:
    score = 0
    if discount_pct > 45: score += 3
    elif discount_pct > 35: score += 1
    dl = len(listing.get("description", "") or "")
    if dl < 50: score += 2
    elif dl < 150: score += 1
    si = listing.get("seller_items", 0)
    if si == 0: score += 2
    elif si < 3: score += 1
    # Bundle penalty — price includes extra items
    if is_bundle(listing): score += 3
    return "low" if score <= 1 else "medium" if score <= 3 else "high"


def compute_score(profit, discount_pct, liquidity, risk, is_deal) -> float:
    if not is_deal: return 0.0
    s  = min(40, profit / 10) + min(30, discount_pct * 0.8)
    s += {"high": 20, "medium": 10, "low": 0}[liquidity]
    s -= {"low": 0, "medium": 5, "high": 15}[risk]
    return round(max(0, min(100, s)), 1)
