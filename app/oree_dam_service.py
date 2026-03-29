"""OREE DAM price sync — ported from Java OreeDamPriceSyncService + OreeDamPriceRepository logic."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app import settings
from app.models import OreeDamPrice

logger = logging.getLogger(__name__)

KYIV = ZoneInfo("Europe/Kiev")


def oree_dam_configured() -> bool:
    return bool(settings.OREE_API_KEY and settings.OREE_API_KEY.strip())


def kyiv_tomorrow() -> date:
    return (datetime.now(KYIV).date() + timedelta(days=1))


def _parse_int(s: str) -> int:
    try:
        return int(s.strip())
    except (TypeError, ValueError):
        return -1


def _parse_double(s: str) -> float:
    try:
        return float(re.sub(r",", ".", str(s).strip()))
    except (TypeError, ValueError):
        return 0.0


def _parse_date(s: str) -> Optional[date]:
    try:
        return date.fromisoformat(str(s).strip()[:10])
    except (TypeError, ValueError):
        return None


def _has_any_hourly(values: list[Optional[float]]) -> bool:
    return any(v is not None for v in values)


async def fetch_oree_dam_json() -> list[dict[str, Any]]:
    """GET OREE /damprices — returns list of day objects (raw JSON)."""
    if not oree_dam_configured():
        logger.warning("OREE DAM: API key empty, skip fetch")
        return []
    url = f"{settings.OREE_API_BASE_URL}{settings.OREE_API_DAM_PRICES_PATH}"
    headers = {"Accept": "application/json", "X-API-KEY": settings.OREE_API_KEY}
    async with httpx.AsyncClient(timeout=45.0) as client:
        r = await client.get(url, headers=headers)
    if r.status_code >= 400:
        logger.warning("OREE DAM HTTP %s — %s", r.status_code, (r.text or "")[:500])
        r.raise_for_status()
    data = r.json()
    if not isinstance(data, list):
        logger.warning("OREE DAM: expected JSON array, got %s", type(data).__name__)
        return []
    return data


async def sync_dam_prices_to_db(session: AsyncSession) -> int:
    """
    Pull DAM from OREE and upsert into oree_dam_price (same fields as Java).
    Returns number of rows written.
    """
    if not oree_dam_configured():
        return 0
    raw_days = await fetch_oree_dam_json()
    saved = 0
    upsert_sql = text(
        """
        INSERT INTO oree_dam_price (trade_day, zone_eic, period, price_uah_mwh, created_on, updated_on)
        VALUES (:trade_day, :zone_eic, :period, :price_uah_mwh, NOW(), NOW())
        ON CONFLICT (trade_day, zone_eic, period) DO UPDATE SET
          price_uah_mwh = EXCLUDED.price_uah_mwh,
          updated_on = NOW()
        """
    )
    for day in raw_days:
        if not isinstance(day, dict):
            continue
        trade_day_s = day.get("trade_day")
        zone_eic = day.get("zone_eic")
        points = day.get("data")
        if trade_day_s is None or zone_eic is None or not isinstance(points, list):
            continue
        trade_day = _parse_date(str(trade_day_s))
        if trade_day is None:
            continue
        zone_eic = str(zone_eic).strip()
        for point in points:
            if not isinstance(point, dict):
                continue
            per = point.get("period")
            price = point.get("price")
            if per is None or price is None:
                continue
            period = _parse_int(str(per))
            if period < 1 or period > 24:
                continue
            price_uah_mwh = _parse_double(str(price))
            await session.execute(
                upsert_sql,
                {
                    "trade_day": trade_day,
                    "zone_eic": zone_eic,
                    "period": period,
                    "price_uah_mwh": price_uah_mwh,
                },
            )
            saved += 1
    await session.commit()
    logger.info("OREE DAM sync: %s row(s) upserted", saved)
    return saved


async def get_hourly_dam_uah_mwh(
    session: AsyncSession,
    trade_day: date,
    zone_eic: str,
) -> list[Optional[float]]:
    """24 values; index 0 = period 1 … index 23 = period 24 (UAH/MWh)."""
    result = await session.execute(
        select(OreeDamPrice.period, OreeDamPrice.price_uah_mwh).where(
            OreeDamPrice.trade_day == trade_day,
            OreeDamPrice.zone_eic == zone_eic,
        )
    )
    by_period: dict[int, float] = {}
    for p, price in result.all():
        if 1 <= int(p) <= 24:
            by_period[int(p)] = float(price)
    return [by_period.get(p) for p in range(1, 25)]


async def get_hourly_dam_with_optional_sync(
    session: AsyncSession,
    trade_day: date,
    zone_eic: str,
) -> tuple[list[Optional[float]], bool]:
    """
    Read DAM from DB; if empty and trade_day is tomorrow (Kyiv), run sync once (Java parity).
    Returns (hourly_uah_mwh, sync_triggered).
    """
    hourly = await get_hourly_dam_uah_mwh(session, trade_day, zone_eic)
    if _has_any_hourly(hourly):
        return hourly, False
    if trade_day == kyiv_tomorrow() and oree_dam_configured():
        logger.info("DAM cache miss for tomorrow (%s), on-demand OREE sync", trade_day)
        await sync_dam_prices_to_db(session)
        hourly = await get_hourly_dam_uah_mwh(session, trade_day, zone_eic)
        return hourly, True
    return hourly, False
