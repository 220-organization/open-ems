"""Shared NBU EUR→UAH (UAH per 1 EUR) for server-side ENTSO-E UAH→EUR conversion and /api/fx."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

NBU_EXCHANGE_URL = "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange"


async def fetch_nbu_eur_row(date_compact: str) -> Optional[dict[str, Any]]:
    """Single-day NBU lookup for EUR (YYYYMMDD)."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(
            NBU_EXCHANGE_URL,
            params={"valcode": "EUR", "date": date_compact, "json": ""},
        )
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list) and data and data[0].get("rate") is not None:
            return data[0]
    return None


async def fetch_eur_uah_rate_for_date(preferred: date) -> Optional[float]:
    """
    Return UAH per 1 EUR for preferred calendar day, or nearest earlier NBU publication (up to 10 days).
    Used when converting ENTSO-E Ukraine prices published in UAH/MWh to EUR/MWh for storage.
    """
    for i in range(10):
        d = preferred - timedelta(days=i)
        compact = d.strftime("%Y%m%d")
        try:
            row = await fetch_nbu_eur_row(compact)
        except httpx.HTTPError as e:
            logger.warning("NBU EUR fetch failed for %s: %s", compact, e)
            return None
        if row is not None:
            rate = row.get("rate")
            if rate is not None and isinstance(rate, (int, float)):
                return float(rate)
    return None
