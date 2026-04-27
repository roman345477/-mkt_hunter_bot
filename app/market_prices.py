"""
Market price engine.
Strategy:
1. Кожні 12 годин підтягує ціни з Marktplaats (медіана ПРОДАНИХ + активних)
2. Використовує p75 від активних оголошень як market price
3. Fallback — статичні ціни досліджені вручну
"""

import logging
import re
import statistics
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ── Статичні ціни (fallback, Apr 2025, Dutch market) ─────────────────────────
STATIC_PRICES: dict[str, dict] = {
    # RTX 50 series
    "RTX 5090": {"market": 4500, "resale": 4100},
    "RTX 5080": {"market": 3200, "resale": 2900},
    "RTX 5070 Ti": {"market": 2400, "resale": 2150},
    "RTX 5070": {"market": 1900, "resale": 1720},
    # RTX 40 series
    "RTX 4090": {"market": 3500, "resale": 3200},
    "RTX 4080": {"market": 2200, "resale": 1980},
    "RTX 4070 Ti": {"market": 1800, "resale": 1620},
    "RTX 4070": {"market": 1450, "resale": 1300},
    "RTX 4060 Ti": {"market": 1250, "resale": 1120},
    "RTX 4060": {"market": 1100, "resale": 990},
    "RTX 4050": {"market":  950, "resale":  860},
    # RTX 30 series
    "RTX 3080 Ti": {"market": 1400, "resale": 1250},
    "RTX 3080": {"market": 1100, "resale":  980},
    "RTX 3070 Ti": {"market":  950, "resale":  850},
    "RTX 3070": {"market":  850, "resale":  760},
    "RTX 3060 Ti": {"market":  700, "resale":  630},
    "RTX 3060": {"market":  650, "resale":  580},
    "RTX 3050": {"market":  550, "resale":  490},
    # GTX series
    "GTX 1660 Ti": {"market": 450, "resale": 400},
    "GTX 1650": {"market": 380, "resale": 340},
}

# ── Динамічний кеш (оновлюється зі скрапів) ──────────────────────────────────
_dynamic: dict[str, dict] = {}
_TTL = timedelta(hours=12)


def percentile(data: list, p: float) -> float:
    if not data: return 0.0
    s = sorted(data)
    k = (len(s) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (k - f) * (s[c] - s[f])


def update_from_listings(all_listings: list):
    """
    Called every scrape cycle.
    Groups listings by GPU, computes p75 as market price.
    Only updates if cache is stale (>12h).
    """
    now = datetime.utcnow()
    by_gpu: dict[str, list] = {}
    for l in all_listings:
        gpu = l.get("gpu", "")
        price = l.get("price", 0)
        if gpu and 200 <= price <= 5000:
            by_gpu.setdefault(gpu, []).append(price)

    for gpu, prices in by_gpu.items():
        cached = _dynamic.get(gpu)
        if cached and (now - cached["updated"]) < _TTL:
            continue
        if len(prices) < 4:
            continue
        p75    = percentile(prices, 75)
        p50    = statistics.median(prices)
        market = round(p75)
        resale = round(p75 * 0.92)
        _dynamic[gpu] = {
            "market":      market,
            "resale":      resale,
            "p50":         round(p50),
            "p75":         round(p75),
            "sample_size": len(prices),
            "updated":     now,
            "source":      "dynamic",
        }
        logger.info(f"💹 {gpu}: market=€{market} resale=€{resale} (n={len(prices)}, p50=€{round(p50)}, p75=€{round(p75)})")


def get(gpu: str) -> dict:
    """Return best available price data for a GPU."""
    d = _dynamic.get(gpu)
    if d:
        return d
    s = STATIC_PRICES.get(gpu)
    if s:
        return {**s, "source": "static", "sample_size": 0, "p75": s["market"]}
    # Unknown GPU — estimate from market cap
    return {"market": 1000, "resale": 900, "source": "unknown", "sample_size": 0, "p75": 1000}


def all_prices_info() -> dict:
    """Return price info for all known GPUs — for API/Mini App."""
    result = {}
    for gpu in STATIC_PRICES:
        d = _dynamic.get(gpu)
        if d:
            result[gpu] = {**d, "updated": d["updated"].isoformat()}
        else:
            result[gpu] = {**STATIC_PRICES[gpu], "source": "static", "sample_size": 0}
    return result


def known_gpus() -> list[str]:
    return list(STATIC_PRICES.keys())
