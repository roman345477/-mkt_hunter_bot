"""
Marktplaats scraper — expanded GPU support, anti-block delays, night pause.
"""

import re
import random
import logging
import asyncio
from datetime import datetime
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

# ── All supported GPU keywords ───────────────────────────────────────────────
GPU_KEYWORDS = {
    # RTX 50
    "RTX 5090":    ["5090"],
    "RTX 5080":    ["5080"],
    "RTX 5070 Ti": ["5070 ti", "5070ti"],
    "RTX 5070":    ["5070"],
    # RTX 40
    "RTX 4090":    ["4090"],
    "RTX 4080":    ["4080"],
    "RTX 4070 Ti": ["4070 ti", "4070ti"],
    "RTX 4070":    ["4070"],
    "RTX 4060 Ti": ["4060 ti", "4060ti"],
    "RTX 4060":    ["4060"],
    "RTX 4050":    ["4050"],
    # RTX 30
    "RTX 3080 Ti": ["3080 ti", "3080ti"],
    "RTX 3080":    ["3080"],
    "RTX 3070 Ti": ["3070 ti", "3070ti"],
    "RTX 3070":    ["3070"],
    "RTX 3060 Ti": ["3060 ti", "3060ti"],
    "RTX 3060":    ["3060"],
    "RTX 3050":    ["3050"],
    # GTX
    "GTX 1660 Ti": ["1660 ti", "1660ti"],
    "GTX 1650":    ["1650"],
}

# Search queries sent to Marktplaats
SEARCH_QUERIES = [
    "RTX 4060 laptop",
    "RTX 4050 laptop",
    "RTX 4070 laptop",
    "RTX 3060 laptop",
    "RTX 3070 laptop",
    "gaming laptop nvidia",
]

MARKTPLAATS_BASE = "https://www.marktplaats.nl"
SEARCH_URL       = "https://www.marktplaats.nl/lrp/api/search"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
]


def is_night_time() -> bool:
    hour = (datetime.utcnow().hour + 1) % 24
    return 0 <= hour < 7


def get_headers() -> dict:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "nl-NL,nl;q=0.9,en-US;q=0.8",
        "Referer": "https://www.marktplaats.nl/",
        "Origin": "https://www.marktplaats.nl",
        "DNT": "1",
    }


def build_params(query: str, max_price: int = 5000) -> dict:
    return {
        "query": query,
        "categoryId": "31",
        "condition": "new,as-good-as-new",
        "priceFrom": "200",
        "priceTo": str(max_price),
        "sortBy": "SORT_INDEX",
        "sortOrder": "DECREASING",
        "offset": 0,
        "limit": 30,
        "searchInTitleAndDescription": "true",
        "attributes": "",
    }


def extract_gpu(text: str) -> Optional[str]:
    t = text.upper()
    # Check Ti variants first (more specific)
    for gpu, keywords in GPU_KEYWORDS.items():
        for kw in keywords:
            if kw.upper() in t:
                return gpu
    return None


def extract_ram(text: str) -> int:
    for pat in [r"(\d+)\s*GB\s*RAM", r"(\d+)\s*GB", r"RAM\s*(\d+)"]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            v = int(m.group(1))
            if v in [4, 8, 12, 16, 24, 32, 48, 64]:
                return v
    return 0


def extract_storage(text: str) -> int:
    """Extract SSD/storage in GB."""
    for pat in [r"(\d+)\s*TB", r"(\d+)\s*GB\s*SSD", r"(\d+)\s*GB\s*NVMe", r"SSD\s*(\d+)"]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            v = int(m.group(1))
            if "TB" in pat.upper():
                return v * 1024
            if 64 <= v <= 4096:
                return v
    return 0


def extract_screen(text: str) -> float:
    """Extract screen size in inches."""
    m = re.search(r'(\d+[.,]\d+)\s*["\']|(\d+[.,]\d+)\s*inch|(\d+[.,]\d+)\s*"', text, re.IGNORECASE)
    if m:
        raw = next(x for x in m.groups() if x)
        try:
            return float(raw.replace(',', '.'))
        except Exception:
            pass
    # also match "15" or "17" standalone
    m2 = re.search(r'\b(13|14|15|16|17|18)\b', text)
    if m2:
        return float(m2.group(1))
    return 0.0


def extract_cpu(text: str) -> str:
    t = text.upper()
    if "I9" in t or "CORE I9" in t: return "i9"
    if "I7" in t or "CORE I7" in t: return "i7"
    if "I5" in t or "CORE I5" in t: return "i5"
    if "RYZEN 9" in t: return "Ryzen 9"
    if "RYZEN 7" in t: return "Ryzen 7"
    if "RYZEN 5" in t: return "Ryzen 5"
    return ""


def map_condition(raw: str) -> str:
    raw = raw.lower().replace("_", " ")
    if "nieuw" in raw or "new" in raw: return "new"
    if "goed" in raw or "good" in raw: return "like_new"
    return "new"


def parse_listing(item: dict) -> Optional[dict]:
    try:
        item_id    = str(item.get("itemId", ""))
        title      = (item.get("title", "") or "").strip()
        price_info = item.get("priceInfo", {})
        price      = (price_info.get("priceCents", 0) or 0) / 100

        if not price or price < 100:
            return None

        description = (item.get("description", "") or "")
        full_text   = title + " " + description
        gpu         = extract_gpu(full_text)
        if not gpu:
            return None

        location_info = item.get("location", {})
        location      = location_info.get("cityName", "") or "Netherlands"
        url_path      = item.get("vipUrl", "")
        url           = f"{MARKTPLAATS_BASE}{url_path}" if url_path.startswith("/") else url_path
        condition     = map_condition(item.get("condition", "").lower())
        seller        = item.get("seller", {})
        images        = item.get("pictures", [])
        image_url     = images[0].get("largeUrl", "") if images else ""
        listed_date   = item.get("date", "") or ""

        return {
            "item_id":      item_id,
            "title":        title,
            "price":        price,
            "gpu":          gpu,
            "ram":          extract_ram(full_text),
            "storage":      extract_storage(full_text),
            "screen":       extract_screen(full_text),
            "cpu":          extract_cpu(full_text),
            "condition":    condition,
            "location":     location,
            "url":          url,
            "description":  description[:500],
            "seller_name":  seller.get("name", ""),
            "seller_items": seller.get("activeItemCount", 0),
            "image_url":    image_url,
            "listed_date":  listed_date,
            "scraped_at":   datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.debug(f"Parse error: {e}")
        return None


async def fetch_query(query: str, max_price: int, client: httpx.AsyncClient) -> list[dict]:
    await asyncio.sleep(random.uniform(2.5, 6))
    try:
        resp = await client.get(
            SEARCH_URL,
            params=build_params(query, max_price),
            headers=get_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        items = resp.json().get("listings", [])
        logger.info(f"Query '{query}': {len(items)} items")
        return [p for item in items if (p := parse_listing(item))]
    except Exception as e:
        logger.error(f"Fetch error '{query}': {e}")
        return []


async def scrape_all(max_price: int = 5000) -> list[dict]:
    if is_night_time():
        logger.info("Night pause — skipping scrape")
        return []

    all_listings = []
    seen_ids     = set()

    async with httpx.AsyncClient(follow_redirects=True) as client:
        for query in SEARCH_QUERIES:
            results = await fetch_query(query, max_price, client)
            for item in results:
                if item["item_id"] not in seen_ids:
                    seen_ids.add(item["item_id"])
                    all_listings.append(item)

    logger.info(f"Scraped {len(all_listings)} unique listings")
    return all_listings
