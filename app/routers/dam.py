"""DAM (OREE) hourly prices from open-ems DB; chart-day is DB-only unless lazy sync is explicitly enabled."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app import settings
from app.oree_dam_service import (
    KYIV,
    ensure_dam_indexes_for_day,
    get_hourly_dam_with_optional_sync,
    get_lazy_oree_chart_meta,
    oree_dam_configured,
    sync_dam_prices_to_db,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dam", tags=["dam"])

_NO_STORE = {"Cache-Control": "no-store, max-age=0, must-revalidate"}


def _kyiv_today() -> date:
    return datetime.now(KYIV).date()


@router.post("/sync")
async def dam_sync_now(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    """
    Fetch DAM from OREE API and upsert into oree_dam_price (requires OREE_API_KEY).

    Disabled unless OREE_DAM_MANUAL_SYNC_ENABLED=1 — normal flow is daily background sync only.
    """
    if not settings.OREE_DAM_MANUAL_SYNC_ENABLED:
        return JSONResponse(
            content={
                "ok": False,
                "configured": oree_dam_configured(),
                "rows": 0,
                "detail": "Manual DAM sync is disabled (set OREE_DAM_MANUAL_SYNC_ENABLED=1 to enable POST /api/dam/sync)",
            },
            status_code=403,
            headers=_NO_STORE,
        )
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
    DAM chart hourly prices: read from DB only (UAH/kWh = MWh/1000).

    OREE is not called from this endpoint when OREE_DAM_LAZY_FETCH_MAX=0. Default is 5 on-demand pulls
    per trade day when DB is empty for Kyiv tomorrow. Otherwise populate prices via the daily scheduler
    (OREE_DAM_DAILY_SYNC_* Europe/Kyiv) or manual POST /api/dam/sync if enabled.
    """
    day = date_param or _kyiv_today()
    zone = settings.OREE_COMPARE_ZONE_EIC

    hourly_mwh, sync_triggered = await get_hourly_dam_with_optional_sync(db, day, zone)
    lazy_oree = await get_lazy_oree_chart_meta(db, day)
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
            "hourlyPriceDamUahMwh": hourly_mwh,
            "hourlyPriceDamUahPerKwh": hourly_dam_uah_per_kwh,
            "oreeConfigured": oree_dam_configured(),
            "syncTriggered": sync_triggered,
            "lazyOree": lazy_oree,
        },
        headers=_NO_STORE,
    )


@router.get("/damindexes")
async def dam_damindexes(
    date_param: Optional[date] = Query(default=None, alias="date"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """
    DAM price indices (DAY/NIGHT/PEAK/HPEAK/BASE) for `date` (YYYY-MM-DD), default Kyiv today.
    Reads `oree_dam_index` first; if empty, calls OREE /damindexes and upserts, then returns.
    Response `data` matches OREE shape (prices in UAH/MWh strings); UI converts to UAH/kWh.
    """
    day = date_param or _kyiv_today()
    if not oree_dam_configured():
        return JSONResponse(
            content={
                "ok": False,
                "configured": False,
                "detail": "OREE_API_KEY not set",
                "data": None,
                "date": day.isoformat(),
            },
            headers=_NO_STORE,
        )
    try:
        data, source = await ensure_dam_indexes_for_day(db, day)
        if data is None:
            return JSONResponse(
                content={
                    "ok": False,
                    "configured": True,
                    "detail": "No DAM index data for this date.",
                    "data": None,
                    "date": day.isoformat(),
                },
                status_code=404,
                headers=_NO_STORE,
            )
        return JSONResponse(
            content={
                "ok": True,
                "configured": True,
                "date": day.isoformat(),
                "source": source,
                "data": data,
            },
            headers=_NO_STORE,
        )
    except Exception as exc:
        logger.exception("damindexes failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
