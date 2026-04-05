"""
Marktplaats scraper — uses requests + rotating headers.
Parses RTX 4050/4060 gaming laptops, avoids blocks.
"""

import time
import random
import logging
import re
import httpx
from datetime import datetime
from typing import Optional
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

SEARCH_QUERIES = [
    "RTX 4060 laptop",
    "RTX 4050 laptop",
]

MARKTPLAATS_BASE = "https://www.marktplaats.nl"
SEARCH_URL = "https://www.marktplaats.nl/lrp/api/search"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]


def get_headers() -> dict:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.marktplaats.nl/",
        "Origin": "https://www.marktplaats.nl",
        "DNT": "1",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }


def build_search_params(query: str, offset: int = 0) -> dict:
    return {
        "query": query,
        "categoryId": "31",          # Computers & Elektronica > Laptops & Netbooks
        "condition": "new,as-good-as-new",
        "priceFrom": "200",
        "priceTo": "1000",
        "distanceMeters": "0",
        "postcode": "",
        "sortBy": "SORT_INDEX",
        "sortOrder": "DECREASING",
        "offset": offset,
        "limit": 30,
        "searchInTitleAndDescription": "true",
        "attributes": "",
    }


def parse_listing(item: dict) -> Optional[dict]:
    """Extract fields from a Marktplaats API listing item."""
    try:
        item_id = str(item.get("itemId", ""))
        title = item.get("title", "").strip()
        price_info = item.get("priceInfo", {})
        price_cents = price_info.get("priceCents", 0)
        price = price_cents / 100 if price_cents else 0

        if not price or price < 100:
            return None

        location_info = item.get("location", {})
        location = location_info.get("cityName", "") or location_info.get("countryName", "Netherlands")

        url_path = item.get("vipUrl", "")
        url = f"{MARKTPLAATS_BASE}{url_path}" if url_path.startswith("/") else url_path

        description = item.get("description", "") or ""

        # Extract GPU from title+description
        gpu = extract_gpu(title + " " + description)
        if not gpu:
            return None

        # Extract RAM
        ram = extract_ram(title + " " + description)

        # Check condition
        condition_raw = item.get("condition", "").lower()
        condition = map_condition(condition_raw)

        # Seller info
        seller = item.get("seller", {})
        seller_name = seller.get("name", "")
        seller_items = seller.get("activeItemCount", 0)

        # Images
        images = item.get("pictures", [])
        image_url = images[0].get("largeUrl", "") if images else ""

        date_str = item.get("date", "")

        return {
            "item_id": item_id,
            "title": title,
            "price": price,
            "gpu": gpu,
            "ram": ram,
            "condition": condition,
            "location": location,
            "url": url,
            "description": description[:500],
            "seller_name": seller_name,
            "seller_items": seller_items,
            "image_url": image_url,
            "raw_date": date_str,
            "scraped_at": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.debug(f"Parse error: {e}")
        return None


def extract_gpu(text: str) -> Optional[str]:
    text = text.upper()
    if "4060" in text:
        return "RTX 4060"
    if "4050" in text:
        return "RTX 4050"
    return None


def extract_ram(text: str) -> int:
    patterns = [r"(\d+)\s*GB\s*RAM", r"(\d+)GB", r"RAM\s*(\d+)"]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            val = int(match.group(1))
            if val in [8, 16, 24, 32, 64]:
                return val
    return 0


def map_condition(raw: str) -> str:
    if "nieuw" in raw or "new" in raw:
        return "new"
    if "goed" in raw or "good" in raw:
        return "like_new"
    return "used"


async def fetch_listings(query: str, client: httpx.AsyncClient) -> list[dict]:
    """Fetch all listings for a query (first page)."""
    listings = []
    params = build_search_params(query, offset=0)

    try:
        await asyncio.sleep(random.uniform(1.5, 3.5))
        resp = await client.get(
            SEARCH_URL,
            params=params,
            headers=get_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        items = data.get("listings", [])
        logger.info(f"Query '{query}': got {len(items)} raw items")

        for item in items:
            parsed = parse_listing(item)
            if parsed:
                listings.append(parsed)

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP {e.response.status_code} for query '{query}'")
    except httpx.TimeoutException:
        logger.error(f"Timeout for query '{query}'")
    except Exception as e:
        logger.error(f"Fetch error for '{query}': {e}")

    return listings


async def scrape_all() -> list[dict]:
    """Run all queries, return deduplicated list."""
    import asyncio
    all_listings = []
    seen_ids = set()

    async with httpx.AsyncClient(follow_redirects=True) as client:
        for query in SEARCH_QUERIES:
            results = await fetch_listings(query, client)
            for item in results:
                if item["item_id"] not in seen_ids:
                    seen_ids.add(item["item_id"])
                    all_listings.append(item)
            await asyncio.sleep(random.uniform(2, 5))

    logger.info(f"Scraped {len(all_listings)} unique listings")
    return all_listings


import asyncio
