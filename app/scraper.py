"""
Marktplaats scraper — strict laptop-only, robust date parsing.
"""

import re
import random
import logging
import asyncio
from datetime import datetime
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

GPU_KEYWORDS = {
    "RTX 5090":    ["5090"],
    "RTX 5080":    ["5080"],
    "RTX 5070 Ti": ["5070 ti", "5070ti"],
    "RTX 5070":    ["5070"],
    "RTX 4090":    ["4090"],
    "RTX 4080":    ["4080"],
    "RTX 4070 Ti": ["4070 ti", "4070ti"],
    "RTX 4070":    ["4070"],
    "RTX 4060 Ti": ["4060 ti", "4060ti"],
    "RTX 4060":    ["4060"],
    "RTX 4050":    ["4050"],
    "RTX 3080 Ti": ["3080 ti", "3080ti"],
    "RTX 3080":    ["3080"],
    "RTX 3070 Ti": ["3070 ti", "3070ti"],
    "RTX 3070":    ["3070"],
    "RTX 3060 Ti": ["3060 ti", "3060ti"],
    "RTX 3060":    ["3060"],
    "RTX 3050":    ["3050"],
    "GTX 1660 Ti": ["1660 ti", "1660ti"],
    "GTX 1650":    ["1650"],
}

# Must contain at least one of these to be a laptop
LAPTOP_KEYWORDS = [
    "laptop", "notebook", "gaming laptop", "gaming notebook",
    "laptops", "15.6", "15,6", "17.3", "17,3",
    "14 inch", "15 inch", "16 inch", "17 inch",
    '14"', '15"', '16"', '17"',
]

# Any of these = immediately disqualify
EXCLUDE_KEYWORDS = [
    "ps5", "playstation", "xbox", "nintendo", "console",
    "desktop", "pc tower", "gaming pc",
    # GPU accessories
    "egpu", "e-gpu", "external gpu", "videokaart", "grafische kaart",
    "graphics card", "gpu adapter", "usb4 gpu", "thunderbolt gpu",
    "gpu card", "adt-", "gpu box",
    # Other devices
    "mini pc", "nuc", "ipad", "tablet",
    "telefoon", "smartphone", "monitor", "scherm",
    "docking", "dock station",
]

SEARCH_QUERIES = [
    "gaming laptop RTX",
    "laptop RTX 4060",
    "laptop RTX 4050",
    "laptop RTX 4070",
    "laptop RTX 3060",
    "laptop RTX 3070",
    "laptop nvidia RTX",
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


def is_laptop(title: str, description: str) -> bool:
    combined = (title + " " + description).lower()

    # Hard exclusions first
    for kw in EXCLUDE_KEYWORDS:
        if kw in combined:
            logger.debug(f"Excluded by '{kw}': {title[:50]}")
            return False

    # Must have laptop keyword
    for kw in LAPTOP_KEYWORDS:
        if kw in combined:
            return True

    # Long title without exclusions might still be laptop
    if len(title) > 30:
        return True

    return False


def parse_listed_date(item: dict) -> str:
    """
    Parse listing date from Marktplaats API.
    Marktplaats returns date in multiple formats:
    - ISO string: "2026-04-25T14:30:00+02:00"
    - Unix ms: 1745584200000
    - Dutch relative: "Vandaag", "Gisteren"
    - Dutch date: "25 apr."
    """
    # Try numeric timestamp first (most reliable)
    for field in ["sortDate", "date", "startDate", "timestamp", "priorityDate"]:
        raw = item.get(field)
        if raw is None:
            continue
        try:
            # Numeric timestamp
            if isinstance(raw, (int, float)) and raw > 0:
                ts = raw / 1000 if raw > 1e10 else raw
                dt = datetime.utcfromtimestamp(ts)
                if 2020 <= dt.year <= 2030:
                    return dt.isoformat()
                continue

            s = str(raw).strip()
            if not s or s in ("null", "undefined", "None"):
                continue

            # Numeric string
            if s.isdigit() and len(s) >= 10:
                n = int(s)
                ts = n / 1000 if n > 1e10 else n
                dt = datetime.utcfromtimestamp(ts)
                if 2020 <= dt.year <= 2030:
                    return dt.isoformat()
                continue

            # ISO string with timezone
            if "T" in s or (len(s) > 8 and "-" in s):
                clean = s.replace("Z", "").split("+")[0].split(".")[0]
                try:
                    dt = datetime.fromisoformat(clean)
                    if 2020 <= dt.year <= 2030:
                        return dt.isoformat()
                except Exception:
                    pass
                continue

            # Dutch relative date
            now = datetime.utcnow()
            sl = s.lower()
            if sl in ("vandaag", "today", "aujourd'hui"):
                return now.replace(hour=12, minute=0, second=0).isoformat()
            if sl in ("gisteren", "yesterday", "hier"):
                from datetime import timedelta
                return (now - timedelta(days=1)).replace(hour=12, minute=0, second=0).isoformat()

            # Dutch date like "25 apr." or "25 apr. 2026"
            DUTCH_MONTHS = {
                "jan": 1, "feb": 2, "mrt": 3, "apr": 4, "mei": 5, "jun": 6,
                "jul": 7, "aug": 8, "sep": 9, "okt": 10, "nov": 11, "dec": 12
            }
            import re
            m = re.match(r"(\d{1,2})\s+(\w{3})\.?\s*(\d{4})?", sl)
            if m:
                day = int(m.group(1))
                mon_str = m.group(2)[:3]
                year = int(m.group(3)) if m.group(3) else now.year
                month = DUTCH_MONTHS.get(mon_str)
                if month:
                    dt = datetime(year, month, day, 12, 0, 0)
                    if 2020 <= dt.year <= 2030:
                        return dt.isoformat()

        except Exception:
            continue

    return ""


def extract_gpu(text: str) -> Optional[str]:
    t = text.upper()
    for gpu, keywords in GPU_KEYWORDS.items():
        for kw in keywords:
            if kw.upper() in t:
                return gpu
    return None


def extract_ram(text: str) -> int:
    for pat in [r"(\d+)\s*GB\s*RAM", r"(\d+)\s*GB\s*DDR", r"(\d+)GB"]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            v = int(m.group(1))
            if v in [4, 8, 12, 16, 24, 32, 48, 64]:
                return v
    return 0


def extract_storage(text: str) -> int:
    for pat in [r"(\d+)\s*TB\s*SSD", r"(\d+)\s*TB", r"(\d+)\s*GB\s*SSD",
                r"(\d+)\s*GB\s*NVMe", r"(\d+)\s*GB\s*M\.2"]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            v = int(m.group(1))
            if "TB" in pat.upper():
                return v * 1024
            if 64 <= v <= 4096:
                return v
    return 0


def extract_screen(text: str) -> float:
    for pat in [
        r'(\d{2}[.,]\d)\s*(?:inch|")',
        r'\b(13|14|15|16|17|18)[.,]\d\b',
        r'\b(13|14|15|16|17|18)\b.*?(?:inch|")',
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1).replace(",", "."))
            except Exception:
                pass
    return 0.0


def extract_cpu(text: str) -> str:
    t = text.upper()
    if "I9" in t: return "i9"
    if "I7" in t: return "i7"
    if "I5" in t: return "i5"
    if "RYZEN 9" in t: return "Ryzen 9"
    if "RYZEN 7" in t: return "Ryzen 7"
    if "RYZEN 5" in t: return "Ryzen 5"
    return ""


def map_condition(raw: str) -> str:
    raw = raw.lower().replace("_", " ")
    if "nieuw" in raw or "new" in raw: return "new"
    if "goed" in raw or "good" in raw: return "like_new"
    return "new"


def build_params(query: str, max_price: int = 5000) -> dict:
    return {
        "query": query,
        "categoryId": "31",
        "condition": "new,as-good-as-new",
        "priceFrom": "100",
        "priceTo": str(max_price),
        "sortBy": "SORT_INDEX",
        "sortOrder": "DECREASING",
        "offset": 0,
        "limit": 30,
        "searchInTitleAndDescription": "true",
        "attributes": "",
    }


def parse_listing(item: dict) -> Optional[dict]:
    try:
        item_id     = str(item.get("itemId", ""))
        title       = (item.get("title", "") or "").strip()
        price_info  = item.get("priceInfo", {})
        price       = (price_info.get("priceCents", 0) or 0) / 100
        description = (item.get("description", "") or "")

        if not price or price < 100:
            return None

        # Laptop check
        if not is_laptop(title, description):
            return None

        full_text = title + " " + description
        gpu = extract_gpu(full_text)
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
        listed_date   = parse_listed_date(item)

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
    await asyncio.sleep(random.uniform(2.5, 6.0))
    try:
        resp = await client.get(
            SEARCH_URL,
            params=build_params(query, max_price),
            headers=get_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        items = resp.json().get("listings", [])
        logger.info(f"Query '{query}': {len(items)} raw items")
        results = [p for item in items if (p := parse_listing(item))]
        logger.info(f"Query '{query}': {len(results)} after laptop filter")
        return results
    except Exception as e:
        logger.error(f"Fetch error '{query}': {e}")
        return []


async def scrape_all(max_price: int = 5000) -> list[dict]:
    if is_night_time():
        logger.info("Night pause — skipping")
        return []

    all_listings: list[dict] = []
    seen_ids: set[str] = set()

    async with httpx.AsyncClient(follow_redirects=True) as client:
        for query in SEARCH_QUERIES:
            results = await fetch_query(query, max_price, client)
            for item in results:
                if item["item_id"] not in seen_ids:
                    seen_ids.add(item["item_id"])
                    all_listings.append(item)

    logger.info(f"Scraped {len(all_listings)} unique laptop listings")
    return all_listings
