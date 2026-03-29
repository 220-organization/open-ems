"""DAM (OREE) prices stored in open-ems DB; chart combines local DAM + 220-km public day-kwh (EV kWh only)."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app import settings
from app.oree_dam_service import (
    get_hourly_dam_with_optional_sync,
    oree_dam_configured,
    sync_dam_prices_to_db,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dam", tags=["dam"])

_NO_STORE = {"Cache-Control": "no-store, max-age=0, must-revalidate"}


def _kyiv_yesterday() -> date:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Europe/Kiev")).date() - timedelta(days=1)


async def _fetch_b2b_hourly_kwh_220(day: date) -> list[Optional[float]]:
    """GET /b2b/public/day-kwh — use only hourlyKwh220 (EV charging volumes)."""
    url = f"{settings.B2B_API_BASE_URL}/b2b/public/day-kwh"
    params = {"date": day.isoformat()}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url, params=params)
    except httpx.RequestError as exc:
        logger.warning("B2B day-kwh transport error: %s", exc)
        raise HTTPException(status_code=502, detail=f"Upstream day-kwh failed: {exc}") from exc
    if r.status_code == 429:
        raise HTTPException(status_code=429, detail="220-km day-kwh rate limit")
    if r.status_code >= 400:
        raise HTTPException(
            status_code=r.status_code,
            detail=(r.text or "Upstream error")[:2000],
        )
    data = r.json()
    raw = data.get("hourlyKwh220") if isinstance(data, dict) else None
    if not isinstance(raw, list) or len(raw) != 24:
        return [None] * 24
    out: list[Optional[float]] = []
    for v in raw:
        try:
            x = float(v)
            out.append(x if x == x else None)  # NaN -> None
        except (TypeError, ValueError):
            out.append(None)
    return out


@router.post("/sync")
async def dam_sync_now(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    """Fetch DAM from OREE API and upsert into oree_dam_price (requires OREE_API_KEY)."""
    if not oree_dam_configured():
        return JSONResponse(
            content={"ok": False, "configured": False, "rows": 0, "detail": "OREE_API_KEY not set"},
            headers=_NO_STORE,
        )
    try:
        n = await sync_dam_prices_to_db(db)
        return JSONResponse(
            content={"ok": True, "configured": True, "rows": n},
            headers=_NO_STORE,
        )
    except Exception as exc:
        logger.exception("DAM sync failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/chart-day")
async def dam_chart_day(
    date_param: Optional[date] = Query(default=None, alias="date"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """
    One response for the DAM chart: hourly EV kWh from 220-km public API (hourlyKwh220 only)
    and hourly DAM from open-ems DB (OREE sync). UAH/kWh line = DAM MWh price / 1000.
    """
    day = date_param or _kyiv_yesterday()
    zone = settings.OREE_COMPARE_ZONE_EIC

    try:
        hourly_kwh_220 = await _fetch_b2b_hourly_kwh_220(day)
    except HTTPException:
        raise

    hourly_mwh, sync_triggered = await get_hourly_dam_with_optional_sync(db, day, zone)
    hourly_dam_uah_per_kwh: list[Optional[float]] = []
    for m in hourly_mwh:
        if m is None:
            hourly_dam_uah_per_kwh.append(None)
        else:
            hourly_dam_uah_per_kwh.append(float(m) / 1000.0)

    return JSONResponse(
        content={
            "ok": True,
            "date": day.isoformat(),
            "zoneEic": zone,
            "hourlyKwh220": hourly_kwh_220,
            "hourlyPriceDamUahMwh": hourly_mwh,
            "hourlyPriceDamUahPerKwh": hourly_dam_uah_per_kwh,
            "oreeConfigured": oree_dam_configured(),
            "syncTriggered": sync_triggered,
        },
        headers=_NO_STORE,
    )
