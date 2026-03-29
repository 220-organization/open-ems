"""DAM (OREE) hourly prices from open-ems DB; optional on-demand OREE sync for Kyiv tomorrow."""

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
    get_hourly_dam_with_optional_sync,
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
    DAM chart data: hourly prices from open-ems DB (OREE upsert).
    If the DB has no rows for the requested day and that day is tomorrow in Kyiv, triggers one OREE sync.
    UAH/kWh = DAM MWh price / 1000.
    """
    day = date_param or _kyiv_today()
    zone = settings.OREE_COMPARE_ZONE_EIC

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
            "hourlyPriceDamUahMwh": hourly_mwh,
            "hourlyPriceDamUahPerKwh": hourly_dam_uah_per_kwh,
            "oreeConfigured": oree_dam_configured(),
            "syncTriggered": sync_triggered,
        },
        headers=_NO_STORE,
    )
